"""AinosOS AI Test Generator - Dependency Analyzer.

Analyzes dependencies between functions, modules, and external libraries.
Generates mock recommendations and dependency graphs for test generation.
Supports Python, C, and Rust dependency analysis.
"""

import ast
import re
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from .signature_analyzer import FunctionSignature, Language


class DependencyType(Enum):
    """Types of dependencies."""
    IMPORT = auto()
    FUNCTION_CALL = auto()
    METHOD_CALL = auto()
    CLASS_INSTANTIATION = auto()
    MODULE_ACCESS = auto()
    EXTERNAL_LIBRARY = auto()
    SYSTEM_CALL = auto()
    FILE_IO = auto()
    DATABASE = auto()
    NETWORK = auto()
    ENVIRONMENT = auto()
    CONFIGURATION = auto()


@dataclass
class Dependency:
    """Represents a single dependency."""
    name: str
    type: DependencyType
    source_location: Optional[str] = None
    line_number: int = 0
    is_external: bool = False
    is_optional: bool = False
    version: Optional[str] = None
    import_path: Optional[str] = None


@dataclass
class MockRecommendation:
    """Recommendation for mocking a dependency."""
    dependency_name: str
    reason: str
    mock_type: str = "unittest.mock.MagicMock"
    methods_to_mock: List[str] = field(default_factory=list)
    properties_to_mock: List[str] = field(default_factory=list)
    return_values: Dict[str, str] = field(default_factory=dict)
    side_effects: List[str] = field(default_factory=list)
    priority: int = 5  # 1-10


@dataclass
class FunctionDependencyGraph:
    """Dependency graph for a function."""
    function_name: str
    dependencies: List[Dependency] = field(default_factory=list)
    dependents: List[str] = field(default_factory=list)
    internal_calls: List[str] = field(default_factory=list)
    external_calls: List[str] = field(default_factory=list)
    mock_recommendations: List[MockRecommendation] = field(default_factory=list)
    suggested_fixtures: List[str] = field(default_factory=list)
    depth: int = 0


@dataclass
class ModuleDependencyMap:
    """Complete dependency map for a module."""
    module_path: str
    functions: Dict[str, FunctionDependencyGraph] = field(default_factory=dict)
    imports: Dict[str, str] = field(default_factory=dict)
    external_packages: Set[str] = field(default_factory=set)
    circular_dependencies: List[Tuple[str, str]] = field(default_factory=list)
    mockable_externals: List[MockRecommendation] = field(default_factory=list)


class DependencyAnalyzer:
    """Analyzes function and module dependencies for test generation.

    Identifies:
    - Import dependencies
    - Function call graphs
    - External library usage
    - I/O, network, and system dependencies
    - Mock candidates
    - Circular dependencies
    """

    # Python standard library modules (not requiring mocking)
    STDLIB_MODULES = {
        "abc", "ast", "asyncio", "base64", "bisect", "builtins", "collections",
        "colorsys", "contextlib", "copy", "csv", "datetime", "decimal",
        "difflib", "enum", "errno", "functools", "gc", "getpass", "glob",
        "gzip", "hashlib", "heapq", "hmac", "html", "http", "importlib",
        "inspect", "io", "itertools", "json", "logging", "lzma", "math",
        "mmap", "multiprocessing", "operator", "os", "pathlib", "pickle",
        "platform", "pprint", "queue", "random", "re", "reprlib", "secrets",
        "shutil", "signal", "socket", "sqlite3", "ssl", "statistics",
        "string", "struct", "subprocess", "sys", "tempfile", "textwrap",
        "threading", "time", "timeit", "tkinter", "traceback", "tracemalloc",
        "typing", "unicodedata", "unittest", "urllib", "uuid", "warnings",
        "weakref", "xml", "xmlrpc", "zipfile", "zlib", "dataclasses",
        "concurrent", "configparser", "argparse", "array", "binascii",
        "calendar", "codecs", "compileall", "configparser", "contextvars",
        "csv", "curses", "dbm", "dis", "distutils", "doctest",
        "email", "filecmp", "fileinput", "fnmatch", "formatter",
        "fractions", "getopt", "gettext", "graphlib", "gzip",
        "hashlib", "idlelib", "imaplib", "imghdr", "imp",
        "inspect", "ipaddress", "json", "keyword", "lib2to3",
        "linecache", "locale", "lzma", "mailbox", "mailcap",
        "marshal", "math", "mimetypes", "modulefinder", "netrc",
        "nis", "nntplib", "numbers", "opcode", "optparse",
        "ossaudiodev", "parser", "pickletools", "pipes", "pkgutil",
        "plistlib", "poplib", "posix", "posixpath", "pprint",
        "profile", "pstats", "pty", "pwd", "py_compile",
        "pyclbr", "pydoc", "queue", "quopri", "random",
        "re", "readline", "reprlib", "resource", "rlcompleter",
        "runpy", "sched", "secrets", "select", "selectors",
        "shelve", "shlex", "shutil", "signal", "site",
        "smtpd", "smtplib", "sndhdr", "socket", "socketserver",
        "spwd", "sqlite3", "ssl", "stat", "statistics",
        "string", "stringprep", "struct", "subprocess", "sunau",
        "symtable", "sys", "sysconfig", "syslog", "tabnanny",
        "tarfile", "telnetlib", "tempfile", "termios", "test",
        "textwrap", "threading", "time", "timeit", "tkinter",
        "token", "tokenize", "trace", "traceback", "tracemalloc",
        "tty", "turtle", "turtledemo", "types", "typing",
        "unicodedata", "unittest", "urllib", "uu", "uuid",
        "venv", "warnings", "wave", "weakref", "webbrowser",
        "winreg", "winsound", "wsgiref", "xdrlib", "xml",
        "xmlrpc", "zipapp", "zipfile", "zipimport", "zlib",
    }

    # Modules that typically require mocking
    MOCK_REQUIRED_PATTERNS = [
        re.compile(r'requests', re.I),
        re.compile(r'flask', re.I),
        re.compile(r'django', re.I),
        re.compile(r'sqlalchemy', re.I),
        re.compile(r'redis', re.I),
        re.compile(r'celery', re.I),
        re.compile(r'pymongo', re.I),
        re.compile(r'psycopg', re.I),
        re.compile(r'mysql', re.I),
        re.compile(r'boto3?', re.I),
        re.compile(r'google\.cloud', re.I),
        re.compile(r'azure', re.I),
        re.compile(r'kubernetes', re.I),
        re.compile(r'pandas', re.I),
        re.compile(r'numpy', re.I),
        re.compile(r'scipy', re.I),
        re.compile(r'matplotlib', re.I),
        re.compile(r'tensorflow', re.I),
        re.compile(r'torch', re.I),
        re.compile(r'opencv', re.I),
        re.compile(r'PIL|pillow', re.I),
        re.compile(r'fastapi', re.I),
        re.compile(r'aiohttp', re.I),
        re.compile(r'sanic', re.I),
        re.compile(r'grpc', re.I),
        re.compile(r'protobuf', re.I),
        re.compile(r'kafka', re.I),
        re.compile(r'rabbitmq', re.I),
        re.compile(r'pika', re.I),
        re.compile(r'elasticsearch', re.I),
        re.compile(r'pytest', re.I),
    ]

    def __init__(self) -> None:
        self._import_cache: Dict[str, Set[str]] = {}

    # ------------------------------------------------------------------ #
    #  Python Dependency Analysis
    # ------------------------------------------------------------------ #

    def analyze_python_dependencies(self, source: str, module_name: str = "") -> ModuleDependencyMap:
        """Analyze Python source for dependencies."""
        dep_map = ModuleDependencyMap(module_path=module_name)

        try:
            tree = ast.parse(source)
        except SyntaxError:
            return dep_map

        # Collect imports
        self._collect_python_imports(tree, dep_map)

        # Analyze function-level dependencies
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_graph = self._analyze_python_function_deps(node, dep_map)
                dep_map.functions[node.name] = func_graph

        # Detect circular dependencies
        self._detect_circular_deps(dep_map)

        # Generate mock recommendations
        self._generate_mock_recommendations(dep_map)

        return dep_map

    def _collect_python_imports(self, tree: ast.AST, dep_map: ModuleDependencyMap) -> None:
        """Collect all import statements from Python AST."""
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    dep_map.imports[alias.asname or alias.name] = alias.name
                    if not self._is_stdlib(alias.name):
                        dep_map.external_packages.add(alias.name.split('.')[0])

            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    for alias in node.names:
                        full_name = f"{node.module}.{alias.name}"
                        dep_map.imports[alias.asname or alias.name] = full_name
                    if not self._is_stdlib(node.module):
                        dep_map.external_packages.add(node.module.split('.')[0])

    def _is_stdlib(self, module_name: str) -> bool:
        """Check if a module is in the Python standard library."""
        base = module_name.split('.')[0]
        return base in self.STDLIB_MODULES

    def _analyze_python_function_deps(self, node: ast.FunctionDef, dep_map: ModuleDependencyMap) -> FunctionDependencyGraph:
        """Analyze dependencies for a single Python function."""
        graph = FunctionDependencyGraph(function_name=node.name)

        for child in ast.walk(node):
            # Function calls
            if isinstance(child, ast.Call):
                func_name = self._get_call_name(child.func)
                if func_name:
                    if self._is_internal_call(func_name, dep_map):
                        graph.internal_calls.append(func_name)
                    else:
                        dep = Dependency(
                            name=func_name,
                            type=DependencyType.FUNCTION_CALL,
                            line_number=child.lineno,
                            is_external=not self._is_internal_call(func_name, dep_map),
                        )
                        graph.dependencies.append(dep)
                        graph.external_calls.append(func_name)

            # Attribute access (method calls)
            if isinstance(child, ast.Attribute):
                if isinstance(child.value, ast.Name):
                    attr_name = f"{child.value.id}.{child.attr}"
                    dep = Dependency(
                        name=attr_name,
                        type=DependencyType.METHOD_CALL,
                        line_number=child.lineno,
                        is_external=child.value.id not in [f.name for f in dep_map.functions.values()],
                    )
                    graph.dependencies.append(dep)

            # Name references
            if isinstance(child, ast.Name):
                if child.id in dep_map.imports:
                    dep = Dependency(
                        name=child.id,
                        type=DependencyType.IMPORT,
                        line_number=child.lineno,
                        is_external=True,
                        import_path=dep_map.imports[child.id],
                    )
                    graph.dependencies.append(dep)

        return graph

    def _get_call_name(self, node: ast.AST) -> Optional[str]:
        """Extract the full name of a function call."""
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return f"{self._get_call_name(node.value)}.{node.attr}" if isinstance(node.value, (ast.Name, ast.Attribute)) else None
        if isinstance(node, ast.Subscript):
            return None
        return None

    def _is_internal_call(self, func_name: str, dep_map: ModuleDependencyMap) -> bool:
        """Check if a function call is to an internal function."""
        # Check if it's a simple name and exists in our function map
        if '.' not in func_name:
            return func_name in dep_map.functions
        # Check if it's a module.function where module is imported
        parts = func_name.split('.')
        if parts[0] in dep_map.imports:
            return False  # External
        return True  # Assume internal

    # ------------------------------------------------------------------ #
    #  C Dependency Analysis
    # ------------------------------------------------------------------ #

    def analyze_c_dependencies(self, source: str, filepath: str = "") -> ModuleDependencyMap:
        """Analyze C source for dependencies."""
        dep_map = ModuleDependencyMap(module_path=filepath)

        # Remove comments
        cleaned = re.sub(r'/\*[\s\S]*?\*/', '', source)
        cleaned = re.sub(r'//.*', '', cleaned)

        # Collect includes
        includes = re.findall(r'#include\s+[<"]([^>"]+)[>"]', cleaned)
        for inc in includes:
            dep_map.imports[inc] = inc
            if not inc.startswith('.'):
                dep_map.external_packages.add(inc)

        # Detect function calls
        func_calls = re.findall(r'\b(\w+)\s*\(', cleaned)
        # Filter out keywords
        keywords = {'if', 'while', 'for', 'switch', 'return', 'sizeof',
                    'ifdef', 'ifndef', 'define', 'include', 'pragma',
                    'elif', 'endif', 'defined', 'error', 'warning',
                    'line', 'undef', 'import', 'elifdef', 'elifndef'}
        for call in func_calls:
            if call not in keywords and not call.startswith('#'):
                dep = Dependency(
                    name=call,
                    type=DependencyType.FUNCTION_CALL,
                    is_external=True,
                )
                # Add to each function's deps
                for func_graph in dep_map.functions.values():
                    func_graph.internal_calls.append(call)
                    func_graph.dependencies.append(dep)

        # Detect system calls
        sys_calls = re.findall(r'\b(fork|exec|system|popen|open|read|write|close|'
                                r'malloc|free|calloc|realloc|printf|scanf|fprintf|'
                                r'sprintf|snprintf|fopen|fclose|fread|fwrite|'
                                r'fseek|ftell|rewind|fflush|socket|bind|listen|'
                                r'accept|connect|send|recv|mmap|munmap|'
                                r'pthread_create|pthread_join|pthread_mutex_lock|'
                                r'pthread_mutex_unlock|exit|atexit|signal|'
                                r'raise|getenv|setenv|putenv)\s*\(', cleaned)
        for call in sys_calls:
            dep = Dependency(
                name=call,
                type=DependencyType.SYSTEM_CALL,
                is_external=True,
            )
            for func_graph in dep_map.functions.values():
                func_graph.dependencies.append(dep)

        # Detect file I/O
        if re.search(r'\bfopen\b', cleaned):
            for func_graph in dep_map.functions.values():
                func_graph.dependencies.append(
                    Dependency(name="file_io", type=DependencyType.FILE_IO, is_external=True)
                )

        return dep_map

    # ------------------------------------------------------------------ #
    #  Rust Dependency Analysis
    # ------------------------------------------------------------------ #

    def analyze_rust_dependencies(self, source: str, filepath: str = "") -> ModuleDependencyMap:
        """Analyze Rust source for dependencies."""
        dep_map = ModuleDependencyMap(module_path=filepath)

        # Remove comments
        cleaned = re.sub(r'/\*[\s\S]*?\*/', '', source)
        cleaned = re.sub(r'//.*', '', cleaned)

        # Collect use statements
        use_pattern = re.compile(r'use\s+(?P<path>[^;]+);')
        for match in use_pattern.finditer(cleaned):
            path = match.group("path").strip()
            # Extract last segment as the local name
            parts = path.split("::")
            local_name = parts[-1].split(" as ")[0].strip()
            if "as " in path:
                local_name = path.split(" as ")[1].strip()
            elif '{' in path:
                # Handle use std::io::{Read, Write}
                base = path.split('{')[0].strip().rstrip('::')
                inner = path.split('{')[1].split('}')[0].strip()
                for item in inner.split(','):
                    item = item.strip()
                    if item and item != 'self':
                        dep_map.imports[item] = f"{base}::{item}"
            else:
                dep_map.imports[local_name] = path
            if not path.startswith("std") and not path.startswith("core") and not path.startswith("alloc"):
                ext_pkg = parts[0]
                dep_map.external_packages.add(ext_pkg)

        # Detect function calls
        fn_calls = re.findall(r'\b(\w+)\s*\(', cleaned)
        keywords = {'if', 'while', 'for', 'loop', 'match', 'return', 'let',
                    'fn', 'impl', 'trait', 'enum', 'struct', 'use', 'mod',
                    'pub', 'self', 'super', 'crate', 'where', 'as', 'in',
                    'ref', 'move', 'async', 'await', 'unsafe', 'dyn',
                    'Some', 'None', 'Ok', 'Err', 'assert', 'assert_eq',
                    'assert_ne', 'println', 'format', 'vec', 'panic'}
        for call in fn_calls:
            if call not in keywords:
                dep = Dependency(
                    name=call,
                    type=DependencyType.FUNCTION_CALL,
                    is_external=True,
                )
                for func_graph in dep_map.functions.values():
                    func_graph.dependencies.append(dep)

        # Detect file I/O
        io_patterns = [r'\bstd::fs::', r'\bstd::io::', r'\bFile::', r'\bOpenOptions']
        if any(re.search(p, cleaned) for p in io_patterns):
            for func_graph in dep_map.functions.values():
                func_graph.dependencies.append(
                    Dependency(name="file_io", type=DependencyType.FILE_IO, is_external=True)
                )

        # Detect network I/O
        net_patterns = [r'\bstd::net::', r'\btcp::', r'\budp::', r'\bTcpStream',
                        r'\bTcpListener\b', r'\bUdpSocket\b']
        if any(re.search(p, cleaned) for p in net_patterns):
            for func_graph in dep_map.functions.values():
                func_graph.dependencies.append(
                    Dependency(name="network_io", type=DependencyType.NETWORK, is_external=True)
                )

        return dep_map

    # ------------------------------------------------------------------ #
    #  Generic Analysis
    # ------------------------------------------------------------------ #

    def analyze(self, source: str, language: Language, filepath: str = "") -> ModuleDependencyMap:
        """Analyze dependencies for source code in the given language."""
        if language == Language.PYTHON:
            return self.analyze_python_dependencies(source, filepath)
        elif language == Language.C:
            return self.analyze_c_dependencies(source, filepath)
        elif language == Language.RUST:
            return self.analyze_rust_dependencies(source, filepath)
        else:
            raise ValueError(f"Unsupported language: {language}")

    def analyze_file(self, filepath: Union[str, Path]) -> ModuleDependencyMap:
        """Analyze dependencies from a source file."""
        path = Path(filepath)
        source = path.read_text(encoding="utf-8", errors="replace")
        ext = path.suffix.lower()

        lang_map = {
            ".py": Language.PYTHON,
            ".c": Language.C,
            ".h": Language.C,
            ".rs": Language.RUST,
        }
        language = lang_map.get(ext)
        if language is None:
            raise ValueError(f"Unsupported file extension: {ext}")

        return self.analyze(source, language, str(path))

    # ------------------------------------------------------------------ #
    #  Circular Dependency Detection
    # ------------------------------------------------------------------ #

    def _detect_circular_deps(self, dep_map: ModuleDependencyMap) -> None:
        """Detect circular dependencies between functions."""
        call_graph: Dict[str, List[str]] = {}
        for func_name, graph in dep_map.functions.items():
            call_graph[func_name] = graph.internal_calls

        visited: Set[str] = set()
        path: List[str] = []

        def dfs(func: str) -> None:
            if func in path:
                cycle_start = path.index(func)
                for i in range(cycle_start, len(path) - 1):
                    dep_map.circular_dependencies.append((path[i], path[i + 1]))
                dep_map.circular_dependencies.append((path[-1], func))
                return
            if func in visited:
                return
            visited.add(func)
            path.append(func)
            for callee in call_graph.get(func, []):
                dfs(callee)
            path.pop()

        for func in call_graph:
            dfs(func)

    # ------------------------------------------------------------------ #
    #  Mock Recommendation Generation
    # ------------------------------------------------------------------ #

    def _generate_mock_recommendations(self, dep_map: ModuleDependencyMap) -> None:
        """Generate mock recommendations based on detected dependencies."""
        for ext_pkg in dep_map.external_packages:
            reason = self._get_mock_reason(ext_pkg)
            if reason:
                rec = MockRecommendation(
                    dependency_name=ext_pkg,
                    reason=reason,
                    mock_type=self._get_mock_type(ext_pkg),
                    priority=self._get_mock_priority(ext_pkg),
                )
                dep_map.mockable_externals.append(rec)

        # Generate per-function mock recommendations
        for func_name, func_graph in dep_map.functions.items():
            for dep in func_graph.dependencies:
                if dep.is_external and dep.type in (
                    DependencyType.FUNCTION_CALL, DependencyType.METHOD_CALL,
                    DependencyType.SYSTEM_CALL, DependencyType.FILE_IO,
                    DependencyType.NETWORK, DependencyType.DATABASE,
                ):
                    rec = MockRecommendation(
                        dependency_name=dep.name,
                        reason=f"External {dep.type.name.lower()} call to '{dep.name}'",
                        mock_type="unittest.mock.MagicMock",
                        priority=7 if dep.type in (DependencyType.DATABASE, DependencyType.NETWORK) else 5,
                    )
                    func_graph.mock_recommendations.append(rec)

    def _get_mock_reason(self, pkg: str) -> Optional[str]:
        """Get the reason why a package should be mocked."""
        for pattern in self.MOCK_REQUIRED_PATTERNS:
            if pattern.search(pkg):
                return f"External package '{pkg}' makes network/IO calls that should be mocked"
        if pkg in ('os', 'sys', 'subprocess', 'shutil', 'signal'):
            return f"System package '{pkg}' interacts with the OS environment"
        if pkg in ('socket', 'ssl', 'urllib', 'http', 'requests', 'aiohttp'):
            return f"Network package '{pkg}' requires mocking for tests"
        if pkg in ('sqlite3', 'psycopg2', 'mysql', 'pymongo', 'redis'):
            return f"Database package '{pkg}' requires mocking or test database"
        if pkg in ('tkinter', 'PyQt5', 'PySide', 'wx'):
            return f"GUI package '{pkg}' requires mocking in headless environments"
        return None

    def _get_mock_type(self, pkg: str) -> str:
        """Get the recommended mock type for a package."""
        if pkg in ('os', 'sys', 'subprocess'):
            return "unittest.mock.patch"
        if pkg in ('requests', 'urllib', 'aiohttp', 'httpx'):
            return "responses.mock or unittest.mock.patch"
        if pkg in ('sqlite3', 'psycopg2', 'mysql', 'pymongo', 'redis'):
            return "unittest.mock.MagicMock"
        return "unittest.mock.MagicMock"

    def _get_mock_priority(self, pkg: str) -> int:
        """Get the priority (1-10) for mocking a package."""
        if pkg in ('requests', 'boto3', 'redis', 'psycopg2', 'mysql', 'pymongo'):
            return 10
        if pkg in ('os', 'sys', 'subprocess', 'socket', 'urllib'):
            return 8
        if pkg in ('flask', 'django', 'fastapi', 'aiohttp', 'httpx'):
            return 9
        if pkg in ('pandas', 'numpy', 'matplotlib'):
            return 4
        if pkg in ('sqlite3', 'tomllib', 'configparser'):
            return 3
        return 5

    # ------------------------------------------------------------------ #
    #  Fixture Suggestions
    # ------------------------------------------------------------------ #

    def suggest_fixtures(self, dep_map: ModuleDependencyMap) -> List[str]:
        """Suggest pytest fixtures based on dependency analysis."""
        fixtures = []

        for ext_pkg in sorted(dep_map.external_packages):
            fixture_name = ext_pkg.replace('.', '_').replace('-', '_')
            if ext_pkg in ('os', 'sys', 'subprocess'):
                fixtures.append(
                    f'@pytest.fixture\ndef mock_{fixture_name}(monkeypatch):\n'
                    f'    """Mock {ext_pkg} calls."""\n'
                    f'    mock = MagicMock()\n'
                    f'    monkeypatch.setattr("{ext_pkg}", mock)\n'
                    f'    return mock\n'
                )
            elif ext_pkg in ('requests', 'urllib'):
                fixtures.append(
                    f'@pytest.fixture\ndef mock_{fixture_name}():\n'
                    f'    """Mock {ext_pkg} HTTP calls."""\n'
                    f'    with patch("{ext_pkg}") as mock:\n'
                    f'        mock_response = MagicMock()\n'
                    f'        mock_response.status_code = 200\n'
                    f'        mock_response.json.return_value = {{}}\n'
                    f'        mock.get.return_value = mock_response\n'
                    f'        mock.post.return_value = mock_response\n'
                    f'        yield mock\n'
                )
            elif ext_pkg in ('sqlite3', 'psycopg2', 'pymongo', 'redis'):
                fixtures.append(
                    f'@pytest.fixture\ndef mock_{fixture_name}():\n'
                    f'    """Mock {ext_pkg} database calls."""\n'
                    f'    with patch("{ext_pkg}") as mock:\n'
                    f'        yield mock\n'
                )
            else:
                fixtures.append(
                    f'@pytest.fixture\ndef mock_{fixture_name}():\n'
                    f'    """Mock {ext_pkg} calls."""\n'
                    f'    mock = MagicMock()\n'
                    f'    return mock\n'
                )

        # Add file I/O fixtures
        has_file_io = any(
            d.type == DependencyType.FILE_IO
            for g in dep_map.functions.values()
            for d in g.dependencies
        )
        if has_file_io:
            fixtures.append(
                '@pytest.fixture\ndef mock_file_io(tmp_path):\n'
                '    """Provide temporary file I/O for tests."""\n'
                '    return tmp_path\n'
            )

        # Add env var fixtures
        has_env = any(
            d.type == DependencyType.ENVIRONMENT
            for g in dep_map.functions.values()
            for d in g.dependencies
        )
        if has_env:
            fixtures.append(
                '@pytest.fixture\ndef mock_env(monkeypatch):\n'
                '    """Mock environment variables."""\n'
                '    monkeypatch.setenv("TEST_MODE", "true")\n'
                '    return monkeypatch\n'
            )

        return fixtures

    # ------------------------------------------------------------------ #
    #  Dependency Report
    # ------------------------------------------------------------------ #

    def generate_report(self, dep_map: ModuleDependencyMap) -> Dict[str, Any]:
        """Generate a comprehensive dependency analysis report."""
        report = {
            "module_path": dep_map.module_path,
            "imports": list(dep_map.imports.items()),
            "external_packages": sorted(dep_map.external_packages),
            "external_count": len(dep_map.external_packages),
            "functions": {},
            "circular_dependencies": [(a, b) for a, b in dep_map.circular_dependencies],
            "mock_recommendations": [],
            "suggested_fixtures": self.suggest_fixtures(dep_map),
        }

        for func_name, func_graph in dep_map.functions.items():
            func_entry = {
                "internal_calls": func_graph.internal_calls,
                "external_calls": func_graph.external_calls,
                "dependency_count": len(func_graph.dependencies),
                "mock_count": len(func_graph.mock_recommendations),
                "mock_recommendations": [
                    {
                        "name": r.dependency_name,
                        "reason": r.reason,
                        "mock_type": r.mock_type,
                        "priority": r.priority,
                    }
                    for r in func_graph.mock_recommendations
                ],
            }
            report["functions"][func_name] = func_entry

        for rec in dep_map.mockable_externals:
            report["mock_recommendations"].append({
                "name": rec.dependency_name,
                "reason": rec.reason,
                "mock_type": rec.mock_type,
                "priority": rec.priority,
            })

        return report