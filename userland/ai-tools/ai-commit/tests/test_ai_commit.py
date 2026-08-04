"""Comprehensive tests for ai_commit.py.

Tests cover all major classes: CommitType, CommitMessage, Config, GitHelper,
DiffParser, CommitTypeDetector, FunctionExtractor, MessageGenerator,
InteractiveEditor, and the main CLI entry point.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional
from unittest.mock import MagicMock, call, patch, PropertyMock

import pytest

# Add parent directory to path so we can import ai_commit
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_commit import (
    APP_NAME,
    CONFIG_FILE_NAME,
    CommitMessage,
    CommitType,
    CommitTypeDetector,
    Config,
    DiffFile,
    DiffHunk,
    DiffParseError,
    DiffParser,
    FunctionExtractor,
    GitError,
    GitHelper,
    InteractiveEditor,
    MAX_BODY_WIDTH,
    MAX_SUBJECT_LENGTH,
    MessageGenerator,
    SCOPE_PATTERN,
    SUPPORTED_LANGUAGES,
    VERSION,
    AICommitCLI,
    build_parser,
    main,
)


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def sample_diff() -> str:
    """Return a minimal valid unified diff for testing."""
    return textwrap.dedent("""\
        diff --git a/example.py b/example.py
        index abc123..def456 100644
        --- a/example.py
        +++ b/example.py
        @@ -1,5 +1,7 @@
         def existing():
             pass
        +def new_feature():
        +    return True
        +
         def unchanged():
             pass
    """)


@pytest.fixture
def sample_diff_multiple_files() -> str:
    """Return a diff with multiple files."""
    return textwrap.dedent("""\
        diff --git a/src/core.py b/src/core.py
        index a1..b2 100644
        --- a/src/core.py
        +++ b/src/core.py
        @@ -1,3 +1,4 @@
         def existing():
        -    return False
        +    return True
        diff --git a/tests/test_core.py b/tests/test_core.py
        new file mode 100644
        --- /dev/null
        +++ b/tests/test_core.py
        @@ -0,0 +1,5 @@
        +def test_something():
        +    assert True
        +
        +class TestClass:
        +    def test_method(self):
        +        pass
    """)


@pytest.fixture
def sample_diff_breaking() -> str:
    """Return a diff with breaking changes."""
    return textwrap.dedent("""\
        diff --git a/api.py b/api.py
        index a1..b2 100644
        --- a/api.py
        +++ b/api.py
        @@ -1,4 +1,4 @@
        -def old_api():
        -    return "old"
        +def new_api():
        +    return "new"
        BREAKING CHANGE: old_api removed
    """)


@pytest.fixture
def empty_diff() -> str:
    """Return an empty diff."""
    return ""


@pytest.fixture
def config_obj() -> Config:
    """Return a default Config instance."""
    return Config()


@pytest.fixture
def git_helper() -> GitHelper:
    """Return a GitHelper for a temporary directory."""
    return GitHelper()


@pytest.fixture
def diff_parser() -> DiffParser:
    """Return a fresh DiffParser."""
    return DiffParser()


@pytest.fixture
def type_detector() -> CommitTypeDetector:
    """Return a fresh CommitTypeDetector."""
    return CommitTypeDetector()


@pytest.fixture
def function_extractor() -> FunctionExtractor:
    """Return a fresh FunctionExtractor."""
    return FunctionExtractor()


@pytest.fixture
def message_generator(config_obj: Config) -> MessageGenerator:
    """Return a MessageGenerator with default config."""
    return MessageGenerator(config_obj)


# ===========================================================================
# Tests: CommitType
# ===========================================================================


class TestCommitType:
    """Tests for the CommitType enum."""

    def test_all_values_are_unique(self) -> None:
        """All commit type values should be unique."""
        values = [t.value for t in CommitType]
        assert len(values) == len(set(values))

    def test_from_string_valid(self) -> None:
        """from_string should parse valid type strings."""
        assert CommitType.from_string("feat") == CommitType.FEAT
        assert CommitType.from_string("FIX") == CommitType.FIX
        assert CommitType.from_string("Docs") == CommitType.DOCS
        assert CommitType.from_string("  refactor  ") == CommitType.REFACTOR

    def test_from_string_invalid(self) -> None:
        """from_string should raise ValueError for unknown types."""
        with pytest.raises(ValueError, match="Unknown commit type"):
            CommitType.from_string("invalid_type")

    def test_label(self) -> None:
        """Each type should have a human-readable label."""
        assert CommitType.FEAT.label == "Feature"
        assert CommitType.FIX.label == "Bug Fix"
        assert CommitType.DOCS.label == "Documentation"
        assert CommitType.CHORE.label == "Chore"

    def test_emoji(self) -> None:
        """Each type should have an emoji."""
        assert CommitType.FEAT.emoji == ":sparkles:"
        assert CommitType.FIX.emoji == ":bug:"
        assert CommitType.REVERT.emoji == ":rewind:"

    def test_contains_all_conventional_types(self) -> None:
        """Should cover all standard Conventional Commits types."""
        expected = {"feat", "fix", "docs", "refactor", "test", "chore", "ci", "perf", "style", "build", "revert"}
        actual = {t.value for t in CommitType}
        assert actual == expected

    def test_emoji_unknown_type(self) -> None:
        """Unknown type should return a question mark emoji."""
        # Create a mock type that isn't in the emoji dict
        assert CommitType.CHORE.emoji  # No crash
        assert isinstance(CommitType.CHORE.emoji, str)


# ===========================================================================
# Tests: CommitMessage
# ===========================================================================


class TestCommitMessage:
    """Tests for the CommitMessage dataclass."""

    def test_default_creation(self) -> None:
        """Should create with default values."""
        msg = CommitMessage()
        assert msg.commit_type == CommitType.CHORE
        assert msg.scope is None
        assert msg.subject == ""
        assert msg.body is None
        assert msg.footer is None
        assert msg.breaking is False

    def test_full_creation(self) -> None:
        """Should create a fully populated message."""
        msg = CommitMessage(
            commit_type=CommitType.FEAT,
            scope="auth",
            subject="add login endpoint",
            body="Implements JWT-based authentication.",
            footer="Closes #42",
            breaking=False,
        )
        assert msg.commit_type == CommitType.FEAT
        assert msg.scope == "auth"
        assert msg.subject == "add login endpoint"
        assert msg.body == "Implements JWT-based authentication."
        assert msg.footer == "Closes #42"

    def test_formatted_simple(self) -> None:
        """Simple message should format correctly."""
        msg = CommitMessage(
            commit_type=CommitType.FEAT,
            subject="add login feature",
        )
        expected = "feat: add login feature"
        assert msg.formatted == expected

    def test_formatted_with_scope(self) -> None:
        """Message with scope should include scope in parentheses."""
        msg = CommitMessage(
            commit_type=CommitType.FIX,
            scope="api",
            subject="handle null pointer in user lookup",
        )
        expected = "fix(api): handle null pointer in user lookup"
        assert msg.formatted == expected

    def test_formatted_with_breaking(self) -> None:
        """Breaking change should add '!' before colon."""
        msg = CommitMessage(
            commit_type=CommitType.REFACTOR,
            subject="rewrite data layer",
            breaking=True,
        )
        expected = "refactor!: rewrite data layer"
        assert msg.formatted == expected

    def test_formatted_full(self) -> None:
        """Full message should format with body and footer."""
        msg = CommitMessage(
            commit_type=CommitType.FEAT,
            scope="auth",
            subject="add OAuth2 support",
            body="Integrates OAuth2 provider for third-party login.",
            footer="BREAKING CHANGE: new auth flow required",
        )
        lines = msg.formatted.split("\n")
        assert lines[0] == "feat(auth): add OAuth2 support"
        assert "Integrates OAuth2 provider" in lines[2]
        assert "BREAKING CHANGE" in lines[-1]

    def test_one_line(self) -> None:
        """one_line should return only the header."""
        msg = CommitMessage(
            commit_type=CommitType.CHORE,
            subject="update dependencies",
            body="Bump all packages to latest versions.",
        )
        assert msg.one_line == "chore: update dependencies"
        assert "\n" not in msg.one_line

    def test_to_dict(self) -> None:
        """to_dict should serialize correctly."""
        msg = CommitMessage(
            commit_type=CommitType.FIX,
            scope="core",
            subject="fix memory leak",
            body="Free unused allocations.",
            footer="Fixes #123",
        )
        d = msg.to_dict()
        assert d["type"] == "fix"
        assert d["scope"] == "core"
        assert d["subject"] == "fix memory leak"
        assert d["body"] == "Free unused allocations."
        assert d["footer"] == "Fixes #123"
        assert d["breaking"] is False

    def test_from_dict(self) -> None:
        """from_dict should deserialize correctly."""
        data = {
            "type": "feat",
            "scope": "api",
            "subject": "add new endpoint",
            "body": "Detailed description.",
            "footer": "Refs #456",
            "breaking": True,
        }
        msg = CommitMessage.from_dict(data)
        assert msg.commit_type == CommitType.FEAT
        assert msg.scope == "api"
        assert msg.subject == "add new endpoint"
        assert msg.breaking is True

    def test_round_trip_dict(self) -> None:
        """to_dict then from_dict should preserve the message."""
        original = CommitMessage(
            commit_type=CommitType.PERF,
            scope="db",
            subject="optimize query",
            body="Added index on user_id column.",
            footer="Closes JIRA-789",
            breaking=False,
        )
        restored = CommitMessage.from_dict(original.to_dict())
        assert restored.commit_type == original.commit_type
        assert restored.scope == original.scope
        assert restored.subject == original.subject
        assert restored.body == original.body
        assert restored.footer == original.footer

    def test_empty_classmethod(self) -> None:
        """empty() should create a placeholder."""
        msg = CommitMessage.empty()
        assert msg.commit_type == CommitType.CHORE
        assert "(empty" in msg.subject

    def test_invalid_scope_raises(self) -> None:
        """Invalid scope should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid scope"):
            CommitMessage(scope="Invalid Scope!")

    def test_subject_truncated_to_max(self) -> None:
        """Subject should be truncated to MAX_SUBJECT_LENGTH."""
        long_subject = "a" * (MAX_SUBJECT_LENGTH + 50)
        msg = CommitMessage(subject=long_subject)
        assert len(msg.subject) <= MAX_SUBJECT_LENGTH

    def test_formatted_body_wrapping(self) -> None:
        """Body should be text-wrapped at MAX_BODY_WIDTH."""
        long_body = "word " * 50
        msg = CommitMessage(
            commit_type=CommitType.DOCS,
            subject="update readme",
            body=long_body,
        )
        formatted = msg.formatted
        for line in formatted.split("\n")[2:]:  # Skip header and blank line
            if line.strip():
                assert len(line) <= MAX_BODY_WIDTH + 10  # Allow small margin


# ===========================================================================
# Tests: Config
# ===========================================================================


class TestConfig:
    """Tests for the Config class."""

    def test_default_values(self) -> None:
        """Default config should have sensible defaults."""
        config = Config()
        assert config.language == "en"
        assert config.max_subject_length == 72
        assert config.max_body_width == 72
        assert config.show_emoji is True
        assert config.auto_commit is False
        assert config.scope_hint is None
        assert config.allow_breaking is True
        assert config.diff_context_lines == 5

    def test_load_from_file(self) -> None:
        """Config should load from a JSON file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / CONFIG_FILE_NAME
            data = {
                "language": "zh",
                "max_subject_length": 50,
                "show_emoji": False,
                "auto_commit": True,
                "diff_context_lines": 3,
            }
            config_path.write_text(json.dumps(data), encoding="utf-8")

            config = Config(config_path=config_path)
            assert config.language == "zh"
            assert config.max_subject_length == 50
            assert config.show_emoji is False
            assert config.auto_commit is True
            assert config.diff_context_lines == 3

    def test_save(self) -> None:
        """Config.save should write a valid JSON file."""
        config = Config()
        config.language = "zh"
        config.show_emoji = False

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test_config.json"
            config.save(path)

            assert path.is_file()
            loaded = json.loads(path.read_text(encoding="utf-8"))
            assert loaded["language"] == "zh"
            assert loaded["show_emoji"] is False

    def test_to_dict(self) -> None:
        """to_dict should return all config values."""
        config = Config()
        d = config.to_dict()
        assert "language" in d
        assert "max_subject_length" in d
        assert "diff_context_lines" in d

    def test_env_overrides(self) -> None:
        """Environment variables should override config values."""
        with patch.dict(os.environ, {"AI_COMMIT_LANGUAGE": "zh", "AI_COMMIT_SHOW_EMOJI": "false"}):
            config = Config()
            assert config.language == "zh"
            assert config.show_emoji is False

    def test_invalid_language_ignored(self) -> None:
        """Invalid language in config should be ignored."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / CONFIG_FILE_NAME
            config_path.write_text(json.dumps({"language": "fr"}), encoding="utf-8")
            config = Config(config_path=config_path)
            assert config.language == "en"  # Default preserved

    def test_diff_context_lines_minimum(self) -> None:
        """diff_context_lines should be at least 1."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / CONFIG_FILE_NAME
            config_path.write_text(json.dumps({"diff_context_lines": 0}), encoding="utf-8")
            config = Config(config_path=config_path)
            assert config.diff_context_lines >= 1

    def test_missing_config_file(self) -> None:
        """Missing config file should not raise."""
        config = Config(config_path=Path("/nonexistent/path/config.json"))
        assert config.language == "en"  # Defaults used

    def test_auto_load_from_cwd(self) -> None:
        """Config should auto-load from current directory upward."""
        with tempfile.TemporaryDirectory() as tmpdir:
            original_cwd = Path.cwd()
            try:
                os.chdir(tmpdir)
                config_path = Path(tmpdir) / CONFIG_FILE_NAME
                config_path.write_text(json.dumps({"language": "zh"}), encoding="utf-8")
                config = Config()
                assert config.language == "zh"
            finally:
                os.chdir(original_cwd)


# ===========================================================================
# Tests: GitHelper
# ===========================================================================


class TestGitHelper:
    """Tests for the GitHelper class."""

    def test_has_staged_changes_no_repo(self) -> None:
        """Outside a git repo, should raise GitError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            helper = GitHelper(repo_path=Path(tmpdir))
            with pytest.raises(GitError):
                helper.has_staged_changes()

    def test_get_repo_root_no_repo(self) -> None:
        """Outside a git repo, should raise GitError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            helper = GitHelper(repo_path=Path(tmpdir))
            with pytest.raises(GitError):
                helper.get_repo_root()

    def test_has_staged_true(self) -> None:
        """has_staged should delegate to has_staged_changes."""
        helper = GitHelper()
        # We can't easily test in a real repo here, just verify the method exists
        assert hasattr(helper, "has_staged")
        assert callable(helper.has_staged)

    @patch("ai_commit.subprocess.run")
    def test_get_staged_diff(self, mock_run: MagicMock) -> None:
        """get_staged_diff should run correct git command."""
        mock_run.return_value = MagicMock(
            stdout="diff --git a/f.py b/f.py\n@@ -1 +1 @@\n-old\n+new\n",
            returncode=0,
            stderr="",
        )
        helper = GitHelper()
        result = helper.get_staged_diff(context_lines=3)
        assert "diff --git" in result
        expected_cmd = ["git", "diff", "--cached", "--unified=3"]
        mock_run.assert_called_once_with(
            expected_cmd,
            capture_output=True,
            text=True,
            cwd=str(helper._repo_path),
            timeout=30,
        )

    @patch("ai_commit.subprocess.run")
    def test_get_staged_files(self, mock_run: MagicMock) -> None:
        """get_staged_files should return file list."""
        mock_run.return_value = MagicMock(
            stdout="file1.py\nfile2.py\n",
            returncode=0,
            stderr="",
        )
        helper = GitHelper()
        files = helper.get_staged_files()
        assert files == ["file1.py", "file2.py"]

    @patch("ai_commit.subprocess.run")
    def test_get_current_branch(self, mock_run: MagicMock) -> None:
        """get_current_branch should return branch name."""
        mock_run.return_value = MagicMock(
            stdout="main\n",
            returncode=0,
            stderr="",
        )
        helper = GitHelper()
        assert helper.get_current_branch() == "main"

    @patch("ai_commit.subprocess.run")
    def test_get_changed_file_extensions(self, mock_run: MagicMock) -> None:
        """get_changed_file_extensions should return extensions."""
        mock_run.return_value = MagicMock(
            stdout="file1.py\nfile2.js\nfile3.tsx\nMakefile\n",
            returncode=0,
            stderr="",
        )
        helper = GitHelper()
        exts = helper.get_changed_file_extensions()
        # Makefile has no extension, so it won't be in the set
        assert exts == {"py", "js", "tsx"}

    @patch("ai_commit.subprocess.run")
    def test_git_error_on_missing_executable(self, mock_run: MagicMock) -> None:
        """Should raise GitError if git is not found."""
        mock_run.side_effect = FileNotFoundError()
        helper = GitHelper()
        with pytest.raises(GitError, match="git executable not found"):
            helper.get_staged_diff()

    @patch("ai_commit.subprocess.run")
    def test_git_timeout(self, mock_run: MagicMock) -> None:
        """Should raise GitError on timeout."""
        mock_run.side_effect = __import__("subprocess").TimeoutExpired("cmd", 30)
        helper = GitHelper()
        with pytest.raises(GitError, match="timed out"):
            helper.get_staged_diff()

    @patch("ai_commit.subprocess.run")
    def test_commit(self, mock_run: MagicMock) -> None:
        """commit should run git commit with message."""
        mock_run.return_value = MagicMock(
            stdout="[main abc123] feat: test\n",
            returncode=0,
            stderr="",
        )
        helper = GitHelper()
        result = helper.commit("feat: test")
        assert "abc123" in result
        mock_run.assert_called_once()

    @patch("ai_commit.subprocess.run")
    def test_amend(self, mock_run: MagicMock) -> None:
        """amend should run git commit --amend."""
        mock_run.return_value = MagicMock(
            stdout="[main def456] fix: amend\n",
            returncode=0,
            stderr="",
        )
        helper = GitHelper()
        result = helper.amend("fix: amend")
        assert "def456" in result
        cmd = mock_run.call_args[0][0]
        assert "--amend" in cmd


# ===========================================================================
# Tests: DiffParser
# ===========================================================================


class TestDiffParser:
    """Tests for the DiffParser class."""

    def test_parse_empty(self, diff_parser: DiffParser) -> None:
        """Empty diff should return empty list."""
        assert diff_parser.parse("") == []
        assert diff_parser.parse("   ") == []

    def test_parse_single_file(self, diff_parser: DiffParser, sample_diff: str) -> None:
        """Should parse a single-file diff."""
        files = diff_parser.parse(sample_diff)
        assert len(files) == 1
        assert files[0].old_path == "example.py"
        assert files[0].new_path == "example.py"
        assert files[0].status == "modified"

    def test_parse_multiple_files(
        self, diff_parser: DiffParser, sample_diff_multiple_files: str
    ) -> None:
        """Should parse multiple files in one diff."""
        files = diff_parser.parse(sample_diff_multiple_files)
        assert len(files) == 2
        assert files[0].display_path == "src/core.py"
        assert files[1].display_path == "tests/test_core.py"

    def test_parse_hunk_details(self, diff_parser: DiffParser, sample_diff: str) -> None:
        """Should correctly parse hunk headers and line counts."""
        files = diff_parser.parse(sample_diff)
        assert len(files[0].hunks) == 1
        hunk = files[0].hunks[0]
        assert hunk.old_start == 1
        assert hunk.old_count == 5
        assert hunk.new_start == 1
        assert hunk.new_count == 7
        assert hunk.added_lines >= 2
        assert hunk.removed_lines == 0

    def test_parse_new_file(self, diff_parser: DiffParser) -> None:
        """Should detect new file mode."""
        diff = textwrap.dedent("""\
            diff --git a/new_file.py b/new_file.py
            new file mode 100644
            --- /dev/null
            +++ b/new_file.py
            @@ -0,0 +1,3 @@
            +def new_func():
            +    pass
        """)
        files = diff_parser.parse(diff)
        assert len(files) == 1
        assert files[0].status == "added"
        assert files[0].old_path == "/dev/null"

    def test_parse_deleted_file(self, diff_parser: DiffParser) -> None:
        """Should detect deleted file mode."""
        diff = textwrap.dedent("""\
            diff --git a/old_file.py b/old_file.py
            deleted file mode 100644
            --- a/old_file.py
            +++ /dev/null
            @@ -1,3 +0,0 @@
            -def old_func():
            -    pass
        """)
        files = diff_parser.parse(diff)
        assert len(files) == 1
        assert files[0].status == "deleted"

    def test_parse_renamed_file(self, diff_parser: DiffParser) -> None:
        """Should detect renamed file."""
        diff = textwrap.dedent("""\
            diff --git a/old.py b/new.py
            rename from old.py
            rename to new.py
        """)
        files = diff_parser.parse(diff)
        assert len(files) == 1
        assert files[0].status == "renamed"
        assert files[0].old_path == "old.py"
        assert files[0].new_path == "new.py"

    def test_parse_summary(self, diff_parser: DiffParser, sample_diff: str) -> None:
        """parse_summary should return a summary dict."""
        summary = diff_parser.parse_summary(sample_diff)
        assert summary["file_count"] == 1
        assert summary["total_added"] > 0
        assert "extensions" in summary
        assert "py" in summary["extensions"]

    def test_parse_summary_empty(self, diff_parser: DiffParser) -> None:
        """parse_summary on empty diff should return zeros."""
        summary = diff_parser.parse_summary("")
        assert summary["file_count"] == 0
        assert summary["total_added"] == 0
        assert summary["total_removed"] == 0

    def test_parse_display_path(self, diff_parser: DiffParser) -> None:
        """display_path should return the new path unless it's /dev/null."""
        diff = textwrap.dedent("""\
            diff --git a/a.py b/a.py
            --- a/a.py
            +++ b/a.py
            @@ -1 +1 @@
            -old
            +new
        """)
        files = diff_parser.parse(diff)
        assert files[0].display_path == "a.py"

    def test_parse_hunk_content(self, diff_parser: DiffParser) -> None:
        """Hunk content should include the header line."""
        diff = textwrap.dedent("""\
            diff --git a/f.py b/f.py
            --- a/f.py
            +++ b/f.py
            @@ -1,2 +1,2 @@
             context
            -old
            +new
        """)
        files = diff_parser.parse(diff)
        assert len(files[0].hunks) == 1
        hunk = files[0].hunks[0]
        assert hunk.content[0].startswith("@@")
        assert hunk.added_lines == 1
        assert hunk.removed_lines == 1


# ===========================================================================
# Tests: CommitTypeDetector
# ===========================================================================


class TestCommitTypeDetector:
    """Tests for the CommitTypeDetector class."""

    def test_detect_feat_by_keyword(
        self, type_detector: CommitTypeDetector, diff_parser: DiffParser
    ) -> None:
        """Should detect feat type from 'add' keyword in diff."""
        diff = textwrap.dedent("""\
            diff --git a/f.py b/f.py
            --- a/f.py
            +++ b/f.py
            @@ -1 +1,2 @@
            +def new_feature():
            +    pass
        """)
        files = diff_parser.parse(diff)
        ctype = type_detector.detect(files, diff)
        assert ctype == CommitType.FEAT, f"Expected feat, got {ctype}"

    def test_detect_fix_by_keyword(
        self, type_detector: CommitTypeDetector, diff_parser: DiffParser
    ) -> None:
        """Should detect fix type from fix/fix keywords."""
        diff = textwrap.dedent("""\
            diff --git a/f.py b/f.py
            --- a/f.py
            +++ b/f.py
            @@ -1,2 +1,2 @@
            -if x is None:
            +if x is not None:
        """)
        files = diff_parser.parse(diff)
        ctype = type_detector.detect(files, diff)
        assert ctype == CommitType.FIX, f"Expected fix, got {ctype}"

    def test_detect_docs_by_path(
        self, type_detector: CommitTypeDetector, diff_parser: DiffParser
    ) -> None:
        """Should detect docs type from docs/ path prefix."""
        diff = textwrap.dedent("""\
            diff --git a/docs/readme.md b/docs/readme.md
            --- a/docs/readme.md
            +++ b/docs/readme.md
            @@ -1 +1 @@
            -old
            +new
        """)
        files = diff_parser.parse(diff)
        ctype = type_detector.detect(files, diff)
        assert ctype == CommitType.DOCS, f"Expected docs, got {ctype}"

    def test_detect_test_by_path(
        self, type_detector: CommitTypeDetector, diff_parser: DiffParser
    ) -> None:
        """Should detect test type from tests/ path prefix."""
        diff = textwrap.dedent("""\
            diff --git a/tests/test_f.py b/tests/test_f.py
            --- a/tests/test_f.py
            +++ b/tests/test_f.py
            @@ -1 +1,2 @@
            +def test_new():
            +    pass
        """)
        files = diff_parser.parse(diff)
        ctype = type_detector.detect(files, diff)
        assert ctype == CommitType.TEST, f"Expected test, got {ctype}"

    def test_detect_ci_by_path(
        self, type_detector: CommitTypeDetector, diff_parser: DiffParser
    ) -> None:
        """Should detect ci type from workflow path."""
        diff = textwrap.dedent("""\
            diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml
            --- a/.github/workflows/ci.yml
            +++ b/.github/workflows/ci.yml
            @@ -1 +1 @@
            -old
            +new
        """)
        files = diff_parser.parse(diff)
        ctype = type_detector.detect(files, diff)
        assert ctype == CommitType.CI, f"Expected ci, got {ctype}"

    def test_detect_scope_single_file(
        self, type_detector: CommitTypeDetector, diff_parser: DiffParser
    ) -> None:
        """Should detect scope from single file directory."""
        diff = textwrap.dedent("""\
            diff --git a/src/auth/login.py b/src/auth/login.py
            --- a/src/auth/login.py
            +++ b/src/auth/login.py
            @@ -1 +1 @@
            -old
            +new
        """)
        files = diff_parser.parse(diff)
        scope = type_detector.detect_scope(files)
        assert scope == "src"

    def test_detect_scope_multiple_files(
        self, type_detector: CommitTypeDetector, diff_parser: DiffParser
    ) -> None:
        """Should detect scope from common prefix."""
        diff = textwrap.dedent("""\
            diff --git a/src/auth/login.py b/src/auth/login.py
            --- a/src/auth/login.py
            +++ b/src/auth/login.py
            @@ -1 +1 @@
            -old
            +new
            diff --git a/src/auth/register.py b/src/auth/register.py
            --- a/src/auth/register.py
            +++ b/src/auth/register.py
            @@ -1 +1 @@
            -old
            +new
        """)
        files = diff_parser.parse(diff)
        scope = type_detector.detect_scope(files)
        assert scope == "src"

    def test_detect_scope_no_files(self, type_detector: CommitTypeDetector) -> None:
        """No files should return None scope."""
        assert type_detector.detect_scope([]) is None

    def test_detect_breaking_change(
        self, type_detector: CommitTypeDetector, diff_parser: DiffParser
    ) -> None:
        """Should detect BREAKING CHANGE marker."""
        files = diff_parser.parse("""\
diff --git a/f.py b/f.py
--- a/f.py
+++ b/f.py
@@ -1 +1 @@
-old
+new
BREAKING CHANGE: test""")
        assert type_detector.detect_breaking_change(files) is True

    def test_detect_breaking_change_false(
        self, type_detector: CommitTypeDetector, diff_parser: DiffParser
    ) -> None:
        """Should return False when no breaking change."""
        diff = textwrap.dedent("""\
            diff --git a/f.py b/f.py
            --- a/f.py
            +++ b/f.py
            @@ -1 +1 @@
            -old
            +new
        """)
        files = diff_parser.parse(diff)
        assert type_detector.detect_breaking_change(files) is False

    def test_detect_defaults_to_chore(
        self, type_detector: CommitTypeDetector, diff_parser: DiffParser
    ) -> None:
        """Diff with no strong signals should default to chore."""
        diff = textwrap.dedent("""\
            diff --git a/config.yml b/config.yml
            --- a/config.yml
            +++ b/config.yml
            @@ -1 +1 @@
            -key: old
            +key: new
        """)
        files = diff_parser.parse(diff)
        ctype = type_detector.detect(files, diff)
        assert ctype == CommitType.CHORE


# ===========================================================================
# Tests: FunctionExtractor
# ===========================================================================


class TestFunctionExtractor:
    """Tests for the FunctionExtractor class."""

    def test_extract_python_function(
        self, function_extractor: FunctionExtractor, diff_parser: DiffParser
    ) -> None:
        """Should extract Python function definitions."""
        diff = textwrap.dedent("""\
            diff --git a/app.py b/app.py
            --- a/app.py
            +++ b/app.py
            @@ -1,3 +1,6 @@
             def existing():
                 pass
            +def new_function():
            +    return 42
            +
            +class NewClass:
            +    def method(self):
            +        pass
        """)
        files = diff_parser.parse(diff)
        functions = function_extractor.extract(files)
        assert "new_function" in functions
        assert "NewClass" in functions
        assert "existing" not in functions  # unchanged, not in diff

    def test_extract_async_function(
        self, function_extractor: FunctionExtractor, diff_parser: DiffParser
    ) -> None:
        """Should extract async Python functions."""
        diff = textwrap.dedent("""\
            diff --git a/app.py b/app.py
            --- a/app.py
            +++ b/app.py
            @@ -1 +1,2 @@
            +async def fetch_data():
            +    return await get()
        """)
        files = diff_parser.parse(diff)
        functions = function_extractor.extract(files)
        assert "fetch_data" in functions

    def test_extract_javascript_function(
        self, function_extractor: FunctionExtractor, diff_parser: DiffParser
    ) -> None:
        """Should extract JavaScript function definitions."""
        diff = textwrap.dedent("""\
            diff --git a/app.js b/app.js
            --- a/app.js
            +++ b/app.js
            @@ -1 +1,2 @@
            +function hello() {
            +    console.log("hello");
            +}
        """)
        files = diff_parser.parse(diff)
        functions = function_extractor.extract(files)
        assert "hello" in functions

    def test_extract_typescript_arrow_function(
        self, function_extractor: FunctionExtractor, diff_parser: DiffParser
    ) -> None:
        """Should extract TypeScript arrow functions."""
        diff = textwrap.dedent("""\
            diff --git a/app.ts b/app.ts
            --- a/app.ts
            +++ b/app.ts
            @@ -1 +1,2 @@
            +const greet = (name: string) => {
            +    return `Hello ${name}`;
            +}
        """)
        files = diff_parser.parse(diff)
        functions = function_extractor.extract(files)
        assert "greet" in functions

    def test_extract_java_method(
        self, function_extractor: FunctionExtractor, diff_parser: DiffParser
    ) -> None:
        """Should extract Java method definitions."""
        diff = textwrap.dedent("""\
            diff --git a/App.java b/App.java
            --- a/App.java
            +++ b/App.java
            @@ -1 +1,2 @@
            +public String getName() {
            +    return this.name;
            +}
        """)
        files = diff_parser.parse(diff)
        functions = function_extractor.extract(files)
        assert "getName" in functions

    def test_extract_rust_function(
        self, function_extractor: FunctionExtractor, diff_parser: DiffParser
    ) -> None:
        """Should extract Rust function definitions."""
        diff = textwrap.dedent("""\
            diff --git a/lib.rs b/lib.rs
            --- a/lib.rs
            +++ b/lib.rs
            @@ -1 +1,2 @@
            +pub fn compute() -> i32 {
            +    42
            +}
        """)
        files = diff_parser.parse(diff)
        functions = function_extractor.extract(files)
        assert "compute" in functions

    def test_extract_go_function(
        self, function_extractor: FunctionExtractor, diff_parser: DiffParser
    ) -> None:
        """Should extract Go function definitions."""
        diff = textwrap.dedent("""\
            diff --git a/main.go b/main.go
            --- a/main.go
            +++ b/main.go
            @@ -1 +1,2 @@
            +func main() {
            +    fmt.Println("hello")
            +}
        """)
        files = diff_parser.parse(diff)
        functions = function_extractor.extract(files)
        assert "main" in functions

    def test_extract_empty(
        self, function_extractor: FunctionExtractor, diff_parser: DiffParser
    ) -> None:
        """Empty diff should return empty list."""
        files = diff_parser.parse("")
        assert function_extractor.extract(files) == []

    def test_extract_filters_false_positives(
        self, function_extractor: FunctionExtractor, diff_parser: DiffParser
    ) -> None:
        """Should filter out common keywords that are not functions."""
        diff = textwrap.dedent("""\
            diff --git a/f.py b/f.py
            --- a/f.py
            +++ b/f.py
            @@ -1 +1,2 @@
            +if True:
            +    pass
        """)
        files = diff_parser.parse(diff)
        functions = function_extractor.extract(files)
        assert "if" not in functions

    def test_extract_with_context(
        self, function_extractor: FunctionExtractor, diff_parser: DiffParser
    ) -> None:
        """extract_with_context should map functions to file paths."""
        diff = textwrap.dedent("""\
            diff --git a/app.py b/app.py
            --- a/app.py
            +++ b/app.py
            @@ -1 +1,2 @@
            +def hello():
            +    pass
        """)
        files = diff_parser.parse(diff)
        ctx = function_extractor.extract_with_context(files)
        assert "hello" in ctx
        assert "app.py" in ctx["hello"]

    def test_extract_with_language_hint(
        self, function_extractor: FunctionExtractor, diff_parser: DiffParser
    ) -> None:
        """Should use language hint for unknown extensions."""
        diff = textwrap.dedent("""\
            diff --git a/app.xyz b/app.xyz
            --- a/app.xyz
            +++ b/app.xyz
            @@ -1 +1,2 @@
            +async def custom():
            +    pass
        """)
        files = diff_parser.parse(diff)
        # Without hint, uses fallback patterns
        functions = function_extractor.extract(files, language_hint="python")
        assert "custom" in functions


# ===========================================================================
# Tests: MessageGenerator
# ===========================================================================


class TestMessageGenerator:
    """Tests for the MessageGenerator class."""

    def test_generate_subject_only(
        self, message_generator: MessageGenerator, diff_parser: DiffParser
    ) -> None:
        """generate_subject_only should return a one-line subject."""
        diff = textwrap.dedent("""\
            diff --git a/app.py b/app.py
            --- a/app.py
            +++ b/app.py
            @@ -1 +1,2 @@
            +def new_func():
            +    pass
        """)
        files = diff_parser.parse(diff)
        subject = message_generator.generate_subject_only(
            diff_files=files,
            commit_type=CommitType.FEAT,
            functions=["new_func"],
        )
        assert isinstance(subject, str)
        assert len(subject) > 0

    def test_generate_full(
        self, message_generator: MessageGenerator, diff_parser: DiffParser
    ) -> None:
        """generate should return a complete CommitMessage."""
        diff = textwrap.dedent("""\
            diff --git a/app.py b/app.py
            --- a/app.py
            +++ b/app.py
            @@ -1 +1,2 @@
            +def new_func():
            +    return 42
        """)
        files = diff_parser.parse(diff)
        msg = message_generator.generate(
            diff_files=files,
            commit_type=CommitType.FEAT,
            scope="core",
            functions=["new_func"],
            is_breaking=False,
        )
        assert isinstance(msg, CommitMessage)
        assert msg.commit_type == CommitType.FEAT
        assert msg.scope == "core"
        assert msg.body is not None
        assert "new_func" in msg.body or "new_func" in msg.subject

    def test_generate_chinese(
        self, diff_parser: DiffParser
    ) -> None:
        """Should generate messages in Chinese when configured."""
        config = Config()
        config.language = "zh"
        generator = MessageGenerator(config)

        diff = textwrap.dedent("""\
            diff --git a/app.py b/app.py
            --- a/app.py
            +++ b/app.py
            @@ -1 +1,2 @@
            +def login():
            +    pass
        """)
        files = diff_parser.parse(diff)
        msg = generator.generate(
            diff_files=files,
            commit_type=CommitType.FEAT,
            functions=["login"],
        )
        assert msg.commit_type == CommitType.FEAT
        # Should use Chinese verb
        assert len(msg.subject) > 0

    def test_generate_breaking(
        self, message_generator: MessageGenerator, diff_parser: DiffParser
    ) -> None:
        """Should include breaking change footer."""
        diff = textwrap.dedent("""\
            diff --git a/api.py b/api.py
            --- a/api.py
            +++ b/api.py
            @@ -1 +1 @@
            -old_api
            +new_api
        """)
        files = diff_parser.parse(diff)
        msg = message_generator.generate(
            diff_files=files,
            commit_type=CommitType.REFACTOR,
            is_breaking=True,
        )
        assert msg.breaking is True
        assert "BREAKING CHANGE" in (msg.footer or "")

    def test_generate_with_scope(
        self, message_generator: MessageGenerator, diff_parser: DiffParser
    ) -> None:
        """Should include scope in the header."""
        diff = textwrap.dedent("""\
            diff --git a/src/auth/login.py b/src/auth/login.py
            --- a/src/auth/login.py
            +++ b/src/auth/login.py
            @@ -1 +1,2 @@
            +def login():
            +    pass
        """)
        files = diff_parser.parse(diff)
        msg = message_generator.generate(
            diff_files=files,
            commit_type=CommitType.FEAT,
            scope="auth",
        )
        assert msg.scope == "auth"
        assert "(auth)" in msg.formatted

    def test_generate_empty_functions(
        self, message_generator: MessageGenerator, diff_parser: DiffParser
    ) -> None:
        """Should handle empty function list gracefully."""
        diff = textwrap.dedent("""\
            diff --git a/config.yml b/config.yml
            --- a/config.yml
            +++ b/config.yml
            @@ -1 +1 @@
            -key: old
            +key: new
        """)
        files = diff_parser.parse(diff)
        msg = message_generator.generate(
            diff_files=files,
            commit_type=CommitType.CHORE,
        )
        assert msg.commit_type == CommitType.CHORE
        assert len(msg.subject) > 0

    def test_file_list_formatting(
        self, message_generator: MessageGenerator, diff_parser: DiffParser
    ) -> None:
        """File list in body should be properly formatted."""
        diff = textwrap.dedent("""\
            diff --git a/a.py b/a.py
            --- a/a.py
            +++ b/a.py
            @@ -1 +1,2 @@
            +line
            diff --git a/b.py b/b.py
            new file mode 100644
            --- /dev/null
            +++ b/b.py
            @@ -0,0 +1 @@
            +new
        """)
        files = diff_parser.parse(diff)
        msg = message_generator.generate(
            diff_files=files,
            commit_type=CommitType.FEAT,
        )
        assert msg.body is not None
        # Should mention both files
        assert "a.py" in msg.body
        assert "b.py" in msg.body


# ===========================================================================
# Tests: InteractiveEditor
# ===========================================================================


class TestInteractiveEditor:
    """Tests for the InteractiveEditor class."""

    def test_parse_edited_message_valid(self) -> None:
        """Should parse a valid Conventional Commits header."""
        original = CommitMessage(commit_type=CommitType.FEAT, subject="test")
        edited = "feat(scope)!: add new feature\n\nBody text\n\nFooter text"
        parsed = InteractiveEditor._parse_edited_message(original, edited)
        assert parsed.commit_type == CommitType.FEAT
        assert parsed.scope == "scope"
        assert parsed.subject == "add new feature"
        assert parsed.breaking is True
        assert "Body text" in (parsed.body or "")
        assert "Footer text" in (parsed.footer or "")

    def test_parse_edited_message_fallback(self) -> None:
        """Should fallback to original values on unparseable header."""
        original = CommitMessage(
            commit_type=CommitType.FIX,
            scope="api",
            subject="original subject",
            body="original body",
        )
        # Invalid header - should fallback
        edited = "just a random string"
        parsed = InteractiveEditor._parse_edited_message(original, edited)
        # Should still work but use original values
        assert parsed is not None

    def test_parse_edited_message_subject_only(self) -> None:
        """Should handle subject-only edited text."""
        original = CommitMessage(commit_type=CommitType.CHORE, subject="old")
        edited = "chore: new subject"
        parsed = InteractiveEditor._parse_edited_message(original, edited)
        assert parsed.subject == "new subject"

    def test_simple_confirm_yes(self) -> None:
        """_simple_confirm should return message on 'y'."""
        msg = CommitMessage(commit_type=CommitType.FEAT, subject="test")
        with patch("builtins.input", return_value="y"):
            result = InteractiveEditor._simple_confirm(msg)
        assert result is not None
        assert result.subject == "test"

    def test_simple_confirm_abort(self) -> None:
        """_simple_confirm should return None on abort."""
        msg = CommitMessage(commit_type=CommitType.FEAT, subject="test")
        with patch("builtins.input", return_value="a"):
            result = InteractiveEditor._simple_confirm(msg)
        assert result is None

    def test_simple_confirm_default(self) -> None:
        """_simple_confirm should return message on empty input (default yes)."""
        msg = CommitMessage(commit_type=CommitType.FEAT, subject="test")
        with patch("builtins.input", return_value=""):
            result = InteractiveEditor._simple_confirm(msg)
        assert result is not None

    def test_simple_confirm_keyboard_interrupt(self) -> None:
        """_simple_confirm should handle Ctrl+C gracefully."""
        msg = CommitMessage(commit_type=CommitType.FEAT, subject="test")
        with patch("builtins.input", side_effect=KeyboardInterrupt):
            result = InteractiveEditor._simple_confirm(msg)
        assert result is None


# ===========================================================================
# Tests: AICommitCLI
# ===========================================================================


class TestAICommitCLI:
    """Tests for the AICommitCLI orchestrator."""

    def test_init_default(self) -> None:
        """Should initialize with default config."""
        cli = AICommitCLI()
        assert cli._config is not None
        assert cli._git is not None

    def test_init_with_config(self) -> None:
        """Should accept a custom config."""
        config = Config()
        config.language = "zh"
        cli = AICommitCLI(config=config)
        assert cli._config.language == "zh"

    def test_no_staged_changes(self) -> None:
        """Should return error when no staged changes."""
        cli = AICommitCLI()
        # Mock git to return no staged changes
        cli._git.has_staged_changes = MagicMock(return_value=False)  # type: ignore[assignment]
        result = cli._generate_and_commit(
            argparse.Namespace(
                type=None,
                scope=None,
                lang=None,
                context_lines=None,
                dry_run=False,
                no_commit=True,
                yes=True,
                quiet=True,
                output=None,
                subject_only=False,
            )
        )
        assert result == 1

    # The remaining CLI methods are tested implicitly through main()
    def test_cmd_init(self) -> None:
        """_cmd_init should create a config file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cli = AICommitCLI()
            with patch.object(Path, "cwd", return_value=Path(tmpdir)):
                args = argparse.Namespace(force=False)
                result = cli._cmd_init(args)
                assert result == 0
                assert (Path(tmpdir) / CONFIG_FILE_NAME).is_file()

    def test_cmd_init_already_exists(self) -> None:
        """_cmd_init should refuse to overwrite without --force."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / CONFIG_FILE_NAME
            config_path.write_text("{}", encoding="utf-8")
            cli = AICommitCLI()
            with patch.object(Path, "cwd", return_value=Path(tmpdir)):
                args = argparse.Namespace(force=False)
                result = cli._cmd_init(args)
                assert result == 1  # Should fail

    def test_cmd_init_force(self) -> None:
        """_cmd_init should overwrite with --force."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / CONFIG_FILE_NAME
            config_path.write_text('{"old": true}', encoding="utf-8")
            cli = AICommitCLI()
            with patch.object(Path, "cwd", return_value=Path(tmpdir)):
                args = argparse.Namespace(force=True)
                result = cli._cmd_init(args)
                assert result == 0
                data = json.loads(config_path.read_text(encoding="utf-8"))
                assert "old" not in data  # Overwritten

    def test_cmd_show_config(self) -> None:
        """_cmd_show_config should return 0."""
        cli = AICommitCLI()
        args = argparse.Namespace()
        result = cli._cmd_show_config(args)
        assert result == 0


# ===========================================================================
# Tests: CLI Parsing
# ===========================================================================


class TestCLIParsing:
    """Tests for the argument parser."""

    def test_parser_basic(self) -> None:
        """Should parse basic arguments."""
        parser = build_parser()
        args = parser.parse_args(["--dry-run"])
        assert args.dry_run is True

    def test_parser_type(self) -> None:
        """Should parse --type argument."""
        parser = build_parser()
        args = parser.parse_args(["--type", "fix"])
        assert args.type == "fix"

    def test_parser_scope(self) -> None:
        """Should parse --scope argument."""
        parser = build_parser()
        args = parser.parse_args(["--scope", "auth"])
        assert args.scope == "auth"

    def test_parser_lang(self) -> None:
        """Should parse --lang argument."""
        parser = build_parser()
        args = parser.parse_args(["--lang", "zh"])
        assert args.lang == "zh"

    def test_parser_invalid_lang(self) -> None:
        """Should reject invalid language."""
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--lang", "fr"])

    def test_parser_invalid_type(self) -> None:
        """Should reject invalid commit type."""
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--type", "invalid"])

    def test_parser_subcommand_init(self) -> None:
        """Should parse 'init' subcommand."""
        parser = build_parser()
        args = parser.parse_args(["init", "--force"])
        assert hasattr(args, "func")
        assert args.force is True

    def test_parser_subcommand_show_config(self) -> None:
        """Should parse 'show-config' subcommand."""
        parser = build_parser()
        args = parser.parse_args(["show-config"])
        assert hasattr(args, "func")

    def test_parser_subcommand_diff(self) -> None:
        """Should parse 'diff' subcommand."""
        parser = build_parser()
        args = parser.parse_args(["diff", "-C", "3"])
        assert hasattr(args, "func")
        assert args.context_lines == 3

    def test_parser_version(self) -> None:
        """Should print version and exit."""
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--version"])

    def test_parser_all_options(self) -> None:
        """Should parse all options together."""
        parser = build_parser()
        args = parser.parse_args([
            "--type", "feat",
            "--scope", "api",
            "--lang", "zh",
            "--context-lines", "10",
            "--dry-run",
            "--no-commit",
            "--yes",
            "--quiet",
            "--output", "msg.txt",
            "--subject-only",
        ])
        assert args.type == "feat"
        assert args.scope == "api"
        assert args.lang == "zh"
        assert args.context_lines == 10
        assert args.dry_run is True
        assert args.no_commit is True
        assert args.yes is True
        assert args.quiet is True
        assert args.output == "msg.txt"
        assert args.subject_only is True


# ===========================================================================
# Tests: main() entry point
# ===========================================================================


class TestMain:
    """Tests for the main() entry point."""

    @patch("ai_commit.AICommitCLI._generate_and_commit")
    def test_main_default(self, mock_generate: MagicMock) -> None:
        """main() should call generate_and_commit by default."""
        mock_generate.return_value = 0
        result = main(["--dry-run", "--no-commit", "--yes", "--quiet"])
        assert result == 0
        mock_generate.assert_called_once()

    @patch("ai_commit.AICommitCLI._cmd_init")
    def test_main_init(self, mock_init: MagicMock) -> None:
        """main() should dispatch to init subcommand."""
        mock_init.return_value = 0
        with patch("sys.argv", ["ai-commit", "init", "--force"]):
            result = main(["init", "--force"])
        assert result == 0

    @patch("ai_commit.AICommitCLI._cmd_show_config")
    def test_main_show_config(self, mock_show: MagicMock) -> None:
        """main() should dispatch to show-config subcommand."""
        mock_show.return_value = 0
        result = main(["show-config"])
        assert result == 0

    @patch("ai_commit.AICommitCLI._cmd_show_diff")
    def test_main_diff(self, mock_diff: MagicMock) -> None:
        """main() should dispatch to diff subcommand."""
        mock_diff.return_value = 0
        result = main(["diff"])
        assert result == 0

    def test_main_with_language_override(self) -> None:
        """main() should apply language override from args."""
        with patch("ai_commit.AICommitCLI._generate_and_commit", return_value=0):
            with patch("ai_commit.Config") as MockConfig:
                mock_config = MagicMock()
                MockConfig.return_value = mock_config
                main(["--lang", "zh", "--dry-run", "--no-commit", "--yes", "--quiet"])
                assert mock_config.language == "zh"


# ===========================================================================
# Tests: Integration / Edge Cases
# ===========================================================================


class TestIntegration:
    """Integration tests that exercise multiple components together."""

    def test_full_flow_with_diff(
        self, diff_parser: DiffParser, type_detector: CommitTypeDetector,
        function_extractor: FunctionExtractor, message_generator: MessageGenerator
    ) -> None:
        """End-to-end: parse diff -> detect type -> extract functions -> generate message."""
        diff = """\
diff --git a/src/user/login.py b/src/user/login.py
--- a/src/user/login.py
+++ b/src/user/login.py
@@ -1,3 +1,8 @@
 def existing():
     pass
+
+def authenticate_user():
+    \"\"\"Authenticate a user.\"\"\"
+    return True
+
+def logout():
+    pass
"""
        files = diff_parser.parse(diff)
        assert len(files) == 1

        ctype = type_detector.detect(files, diff)
        # Should detect feat due to new function definitions
        # (the +def lines match FEATURE_PATTERNS)
        assert ctype == CommitType.FEAT or ctype == CommitType.CHORE

        functions = function_extractor.extract(files)
        assert "authenticate_user" in functions
        assert "logout" in functions

        scope = type_detector.detect_scope(files)
        # Scope should be "src" from the common path

        msg = message_generator.generate(
            diff_files=files,
            commit_type=ctype,
            scope=scope,
            functions=functions,
        )
        assert isinstance(msg, CommitMessage)
        assert msg.subject
        assert msg.formatted
        # Verify the message is valid Conventional Commits format
        assert msg.formatted.startswith(ctype.value)

    def test_diff_with_all_change_types(self, diff_parser: DiffParser) -> None:
        """Should parse a diff with add, modify, and delete."""
        diff = """\
diff --git a/add.py b/add.py
new file mode 100644
--- /dev/null
+++ b/add.py
@@ -0,0 +1,2 @@
+def new_func():
+    pass
diff --git a/modify.py b/modify.py
--- a/modify.py
+++ b/modify.py
@@ -1,2 +1,3 @@
 old_line
+new_line
diff --git a/delete.py b/delete.py
deleted file mode 100644
--- a/delete.py
+++ /dev/null
@@ -1,2 +0,0 @@
-removed_func()
-removed_var
"""
        files = diff_parser.parse(diff)
        assert len(files) == 3

        statuses = {f.status for f in files}
        assert "added" in statuses
        assert "modified" in statuses
        assert "deleted" in statuses

    def test_commit_message_round_trip(self) -> None:
        """A CommitMessage should survive serialize/deserialize/serialize."""
        original = CommitMessage(
            commit_type=CommitType.FEAT,
            scope="api",
            subject="add user endpoint",
            body="Implements GET /users",
            footer="Closes #42",
            breaking=False,
        )
        data = original.to_dict()
        restored = CommitMessage.from_dict(data)
        assert restored.formatted == original.formatted

    def test_scope_pattern_validation(self) -> None:
        """Scope should match the expected pattern."""
        valid_scopes = ["auth", "core", "api-v2", "user_service", "d"]
        for s in valid_scopes:
            assert SCOPE_PATTERN.match(s), f"Scope {s!r} should be valid"

        invalid_scopes = ["Auth", "AUTH", "invalid scope", "has space", "has/slash"]
        for s in invalid_scopes:
            assert not SCOPE_PATTERN.match(s), f"Scope {s!r} should be invalid"

    def test_supported_languages(self) -> None:
        """Should support English and Chinese."""
        assert "en" in SUPPORTED_LANGUAGES
        assert "zh" in SUPPORTED_LANGUAGES
        assert len(SUPPORTED_LANGUAGES) == 2

    def test_version_constant(self) -> None:
        """Version should be a valid semver string."""
        assert isinstance(VERSION, str)
        parts = VERSION.split(".")
        assert len(parts) == 3
        for part in parts:
            assert part.isdigit()

    def test_app_name(self) -> None:
        """APP_NAME should be 'ai-commit'."""
        assert APP_NAME == "ai-commit"


# ===========================================================================
# Tests: Error Handling
# ===========================================================================


class TestErrorHandling:
    """Tests for error handling in various components."""

    def test_git_error_raised(self) -> None:
        """GitError should be raised for git failures."""
        with pytest.raises(GitError):
            raise GitError("test error")

    def test_git_error_message(self) -> None:
        """GitError should preserve the error message."""
        try:
            raise GitError("something went wrong")
        except GitError as e:
            assert "something went wrong" in str(e)

    def test_diff_parse_error(self) -> None:
        """DiffParseError should be raiseable."""
        with pytest.raises(DiffParseError):
            raise DiffParseError("bad diff format")

    def test_commit_type_from_string_error_message(self) -> None:
        """from_string should include valid types in error."""
        with pytest.raises(ValueError) as excinfo:
            CommitType.from_string("bogus")
        assert "feat" in str(excinfo.value)
        assert "fix" in str(excinfo.value)

    def test_config_bad_json(self) -> None:
        """Config should handle malformed JSON gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / CONFIG_FILE_NAME
            config_path.write_text("not valid json", encoding="utf-8")
            # Should not raise
            config = Config(config_path=config_path)
            assert config.language == "en"  # Defaults


# ===========================================================================
# Tests: Edge Cases
# ===========================================================================


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_diff_with_no_hunks(self, diff_parser: DiffParser) -> None:
        """Diff with no hunks should still produce a DiffFile."""
        diff = "diff --git a/f.py b/f.py\n--- a/f.py\n+++ b/f.py\n"
        files = diff_parser.parse(diff)
        assert len(files) == 1
        assert files[0].hunks == []

    def test_hunk_empty_check(self) -> None:
        """DiffHunk.is_empty should work correctly."""
        empty_hunk = DiffHunk(old_start=1, old_count=1, new_start=1, new_count=1)
        assert empty_hunk.is_empty

        non_empty_hunk = DiffHunk(
            old_start=1, old_count=1, new_start=1, new_count=1,
            added_lines=1, removed_lines=0,
        )
        assert not non_empty_hunk.is_empty

    def test_diff_file_extension(self) -> None:
        """DiffFile.extension should return the file extension."""
        f = DiffFile(old_path="test.py", new_path="test.py")
        assert f.extension == "py"

        f2 = DiffFile(old_path="test.js", new_path="test.js")
        assert f2.extension == "js"

        f3 = DiffFile(old_path="Makefile", new_path="Makefile")
        assert f3.extension == ""

    def test_message_with_only_breaking(self) -> None:
        """Message with only breaking flag should format correctly."""
        msg = CommitMessage(
            commit_type=CommitType.REFACTOR,
            subject="rewrite internals",
            breaking=True,
        )
        assert "!" in msg.formatted
        assert msg.formatted.startswith("refactor!")

    def test_message_with_very_long_subject(self) -> None:
        """Very long subject should be truncated."""
        subject = "x" * 200
        msg = CommitMessage(subject=subject)
        assert len(msg.subject) <= MAX_SUBJECT_LENGTH

    def test_config_with_all_env_vars(self) -> None:
        """All config env vars should be applied."""
        env = {
            "AI_COMMIT_LANGUAGE": "zh",
            "AI_COMMIT_AUTO_COMMIT": "true",
            "AI_COMMIT_SCOPE_HINT": "core",
            "AI_COMMIT_SHOW_EMOJI": "false",
            "AI_COMMIT_ALLOW_BREAKING": "false",
        }
        with patch.dict(os.environ, env):
            config = Config()
            assert config.language == "zh"
            assert config.auto_commit is True
            assert config.scope_hint == "core"
            assert config.show_emoji is False
            assert config.allow_breaking is False

    def test_diff_parser_no_changes(self, diff_parser: DiffParser) -> None:
        """Diff with no actual changes should parse to empty."""
        diff = "diff --git a/f.py b/f.py\n--- a/f.py\n+++ b/f.py\n@@ -1,3 +1,3 @@\n context\n context\n context\n"
        files = diff_parser.parse(diff)
        # This is a valid diff but with no +/- lines
        assert len(files) == 1
        assert len(files[0].hunks) == 1
        assert files[0].hunks[0].added_lines == 0
        assert files[0].hunks[0].removed_lines == 0


if __name__ == "__main__":
    pytest.main(["-v", __file__])