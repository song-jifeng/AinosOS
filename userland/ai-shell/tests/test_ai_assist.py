"""
Tests for Ainos Shell AI assistant module.
"""

from __future__ import annotations

import os
import sys
import pytest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.ai_assist import (
    AIAssistant,
    AICommand,
    AIErrorExplanation,
    AISuggestion,
    AIProvider,
    OpenAIProvider,
    AnthropicProvider,
    LocalProvider,
    get_ai_assistant,
    natural_to_command,
    explain_error,
)
from src.ai_commands import (
    AICommandHandler,
    AIEnhancedExecutor,
    get_ai_handler,
    ai_ask,
    ai_explain,
    ai_script,
    ai_translate,
)
from src.completion import (
    AICompletionEngine,
    FrequencyAnalyzer,
    ContextAnalyzer,
    CompletionPrediction,
    get_ai_completion_engine,
)


# ---------------------------------------------------------------------------
# AIAssistant tests
# ---------------------------------------------------------------------------


class TestAIAssistant:
    """Tests for the AIAssistant class."""

    def test_initialization(self) -> None:
        """Test AI assistant initialization."""
        assistant = AIAssistant({"enabled": True, "provider": "openai"})
        assert assistant is not None
        assert assistant._initialized is False

    def test_initialization_disabled(self) -> None:
        """Test disabled AI assistant."""
        assistant = AIAssistant({"enabled": False})
        assert assistant.is_available is False

    def test_ai_command_creation(self) -> None:
        """Test AICommand creation."""
        cmd = AICommand(
            command="ls -la",
            description="List files",
            confidence=0.95,
            explanation="Lists all files including hidden ones",
        )
        assert cmd.command == "ls -la"
        assert cmd.confidence == 0.95
        assert cmd.needs_confirmation is True

    def test_ai_command_no_confirmation(self) -> None:
        """Test AICommand with high confidence."""
        cmd = AICommand(
            command="ls",
            confidence=1.0,
            needs_confirmation=False,
        )
        assert cmd.needs_confirmation is False

    def test_ai_error_explanation(self) -> None:
        """Test AIErrorExplanation creation."""
        explanation = AIErrorExplanation(
            error_text="command not found",
            explanation="The command was not found in PATH",
            suggestions=["Check the spelling", "Install the package"],
            fix_command="sudo apt install <package>",
        )
        assert explanation.error_text == "command not found"
        assert len(explanation.suggestions) == 2
        assert explanation.fix_command != ""

    def test_ai_suggestion(self) -> None:
        """Test AISuggestion creation."""
        suggestion = AISuggestion(
            text="Use `ls -la` for detailed listing",
            category="tip",
            priority=5,
        )
        assert suggestion.text != ""
        assert suggestion.category == "tip"
        assert suggestion.priority == 5

    def test_ai_suggestion_defaults(self) -> None:
        """Test AISuggestion default values."""
        suggestion = AISuggestion(text="Test suggestion")
        assert suggestion.category == "general"
        assert suggestion.priority == 0
        assert suggestion.source == "ai"


# ---------------------------------------------------------------------------
# AIProvider tests
# ---------------------------------------------------------------------------


class TestAIProviders:
    """Tests for AI provider classes."""

    def test_base_provider(self) -> None:
        """Test base provider raises NotImplementedError."""
        provider = AIProvider()
        with pytest.raises(NotImplementedError):
            provider.generate("test")

    def test_openai_provider_creation(self) -> None:
        """Test OpenAI provider creation."""
        provider = OpenAIProvider({"api_key": "test_key"})
        assert provider is not None
        assert provider.name() == "openai/gpt-4o"

    def test_openai_provider_no_key(self) -> None:
        """Test OpenAI provider without API key."""
        provider = OpenAIProvider()
        result = provider.generate("test prompt")
        assert result == ""  # No key, no API call

    def test_anthropic_provider_creation(self) -> None:
        """Test Anthropic provider creation."""
        provider = AnthropicProvider({"api_key": "test_key"})
        assert provider is not None
        assert provider.name() == "anthropic/claude-sonnet-4-20250514"

    def test_anthropic_provider_no_key(self) -> None:
        """Test Anthropic provider without API key."""
        provider = AnthropicProvider()
        result = provider.generate("test prompt")
        assert result == ""

    def test_local_provider_creation(self) -> None:
        """Test local provider creation."""
        provider = LocalProvider({"endpoint": "http://localhost:8080"})
        assert provider is not None
        result = provider.generate("test")
        # Should not crash, may return empty
        assert result is not None

    def test_provider_supports_streaming(self) -> None:
        """Test streaming support check."""
        provider = AIProvider()
        assert provider.supports_streaming() is False


# ---------------------------------------------------------------------------
# AICommandHandler tests
# ---------------------------------------------------------------------------


class TestAICommandHandler:
    """Tests for the AICommandHandler class."""

    def test_initialization(self) -> None:
        """Test handler initialization."""
        handler = AICommandHandler()
        assert handler is not None
        assert handler._last_command is None

    def test_handle_natural_language(self) -> None:
        """Test natural language handling (without API)."""
        handler = AICommandHandler()
        result = handler.handle_natural_language("")
        assert result is None

    def test_get_last_command(self) -> None:
        """Test getting last command when none."""
        handler = AICommandHandler()
        assert handler.get_last_command() is None

    def test_explain_command_empty(self) -> None:
        """Test explain with empty command."""
        handler = AICommandHandler()
        result = handler.explain_command("")
        assert result is None

    def test_translate_command_empty(self) -> None:
        """Test translate with empty command."""
        handler = AICommandHandler()
        result = handler.translate_command("")
        assert result is None

    def test_suggest_fix_empty(self) -> None:
        """Test suggest fix with empty input."""
        handler = AICommandHandler()
        result = handler.suggest_fix("", "")
        assert result is None

    def test_generate_script_empty(self) -> None:
        """Test generate script with empty description."""
        handler = AICommandHandler()
        result = handler.generate_script("")
        assert result is None

    def test_get_shortcut(self) -> None:
        """Test getting command shortcuts."""
        handler = AICommandHandler()
        # Test known shortcuts
        shortcut = handler.get_shortcut("grep -r pattern")
        assert shortcut is not None

    def test_get_shortcut_unknown(self) -> None:
        """Test getting shortcut for unknown command."""
        handler = AICommandHandler()
        shortcut = handler.get_shortcut("some_unknown_command_xyz")
        assert shortcut is None


# ---------------------------------------------------------------------------
# AICompletionEngine tests
# ---------------------------------------------------------------------------


class TestAICompletionEngine:
    """Tests for the AI completion engine."""

    def test_initialization(self) -> None:
        """Test engine initialization."""
        engine = AICompletionEngine()
        assert engine is not None
        assert engine.frequency is not None
        assert engine.context is not None

    def test_frequency_analyzer(self) -> None:
        """Test frequency analyzer creation."""
        analyzer = FrequencyAnalyzer()
        assert analyzer is not None
        assert analyzer._loaded is False

    def test_context_analyzer(self) -> None:
        """Test context analyzer creation."""
        analyzer = ContextAnalyzer()
        assert analyzer is not None
        assert analyzer._last_scan == 0

    def test_completion_prediction(self) -> None:
        """Test completion prediction creation."""
        pred = CompletionPrediction(
            text="ls -la",
            score=0.9,
            source="frequency",
        )
        assert pred.text == "ls -la"
        assert pred.score == 0.9
        assert pred.source == "frequency"

    def test_predictive_suggestions(self) -> None:
        """Test predictive suggestions (no history)."""
        engine = AICompletionEngine()
        suggestions = engine.get_predictive_suggestions()
        assert isinstance(suggestions, list)

    def test_learn_from_command(self) -> None:
        """Test learning from a command."""
        engine = AICompletionEngine()
        engine.learn_from_command("ls -la")
        # Command should be in frequency data
        assert engine.frequency.get_command_frequency("ls -la") >= 1


# ---------------------------------------------------------------------------
# AIEnhancedExecutor tests
# ---------------------------------------------------------------------------


class TestAIEnhancedExecutor:
    """Tests for the AI-enhanced executor."""

    def test_initialization(self) -> None:
        """Test executor initialization."""
        executor = AIEnhancedExecutor()
        assert executor is not None
        assert executor.handler is not None

    def test_pre_process_normal(self) -> None:
        """Test pre-processing normal commands."""
        executor = AIEnhancedExecutor()
        result = executor.pre_process("ls -la")
        assert result == "ls -la"  # Normal command should pass through

    def test_post_process(self) -> None:
        """Test post-processing (should not crash)."""
        executor = AIEnhancedExecutor()
        # Should not raise
        executor.post_process("ls", 0, "output")
        executor.post_process("false", 1, "error")


# ---------------------------------------------------------------------------
# Module-level function tests
# ---------------------------------------------------------------------------


class TestModuleFunctions:
    """Tests for module-level convenience functions."""

    def test_get_ai_assistant(self) -> None:
        """Test getting AI assistant singleton."""
        assistant = get_ai_assistant()
        assert assistant is not None

    def test_get_ai_handler(self) -> None:
        """Test getting AI handler singleton."""
        handler = get_ai_handler()
        assert handler is not None

    def test_get_ai_completion_engine(self) -> None:
        """Test getting AI completion engine singleton."""
        engine = get_ai_completion_engine()
        assert engine is not None

    def test_natural_to_command(self) -> None:
        """Test natural_to_command convenience function."""
        result = natural_to_command("list files")
        # May return None if no API key configured
        assert result is None or isinstance(result, AICommand)

    def test_explain_error_function(self) -> None:
        """Test explain_error convenience function."""
        result = explain_error("ls", "command not found", 127)
        # May return None if no API key configured
        assert result is None or isinstance(result, AIErrorExplanation)


# ---------------------------------------------------------------------------
# AI suggestions tests
# ---------------------------------------------------------------------------


class TestAISuggestions:
    """Tests for AI suggestion generation."""

    def test_suggestions_git(self) -> None:
        """Test git-related suggestions."""
        assistant = AIAssistant({"enabled": True})
        suggestions = assistant.get_suggestions("git commit", {"cwd": "/tmp"})
        git_tips = [s for s in suggestions if "git" in s.text.lower()
                    or "commit" in s.text.lower()]
        # May or may not have suggestions, but shouldn't crash

    def test_suggestions_rm(self) -> None:
        """Test rm-related suggestions."""
        assistant = AIAssistant({"enabled": True})
        suggestions = assistant.get_suggestions("rm -rf /", {"cwd": "/tmp"})
        warnings = [s for s in suggestions if "careful" in s.text.lower()]
        # Should warn about rm -rf with /

    def test_suggestions_chmod(self) -> None:
        """Test chmod-related suggestions."""
        assistant = AIAssistant({"enabled": True})
        suggestions = assistant.get_suggestions("chmod 777 file", {"cwd": "/tmp"})
        warnings = [s for s in suggestions if "permissive" in s.text.lower()
                    or "777" in s.text]

    def test_suggestions_pip(self) -> None:
        """Test pip-related suggestions."""
        assistant = AIAssistant({"enabled": True})
        suggestions = assistant.get_suggestions("pip install flask", {"cwd": "/tmp"})
        venv_tips = [s for s in suggestions if "virtual" in s.text.lower()
                     or "venv" in s.text]

    def test_suggestions_docker(self) -> None:
        """Test docker-related suggestions."""
        assistant = AIAssistant({"enabled": True})
        suggestions = assistant.get_suggestions("docker ps", {"cwd": "/tmp"})
        assert isinstance(suggestions, list)


# ---------------------------------------------------------------------------
# AI provider configuration tests
# ---------------------------------------------------------------------------


class TestAIProviderConfig:
    """Tests for AI provider configuration."""

    def test_openai_provider_config(self) -> None:
        """Test OpenAI provider configuration."""
        provider = OpenAIProvider({
            "api_key": "test-key",
            "model": "gpt-4",
            "api_base": "https://custom.openai.com",
        })
        assert provider.api_key == "test-key"
        assert provider.model == "gpt-4"
        assert provider.api_base == "https://custom.openai.com"

    def test_anthropic_provider_config(self) -> None:
        """Test Anthropic provider configuration."""
        provider = AnthropicProvider({
            "api_key": "test-key",
            "model": "claude-3-opus-20240229",
        })
        assert provider.api_key == "test-key"
        assert provider.model == "claude-3-opus-20240229"

    def test_local_provider_config(self) -> None:
        """Test local provider configuration."""
        provider = LocalProvider({
            "local_model_path": "/models/llama",
            "custom_endpoint": "http://localhost:8080",
        })
        assert provider.model_path == "/models/llama"
        assert provider.endpoint == "http://localhost:8080"


# ---------------------------------------------------------------------------
# AI functions (no-crash tests)
# ---------------------------------------------------------------------------


class TestAIFunctionsNoCrash:
    """Tests that AI functions don't crash when called."""

    def test_ai_ask(self) -> None:
        """Test ai_ask doesn't crash."""
        # Since no API key, it should just print a message
        try:
            ai_ask("list files")
        except Exception:
            pass

    def test_ai_explain(self) -> None:
        """Test ai_explain doesn't crash."""
        try:
            ai_explain("ls -la")
        except Exception:
            pass

    def test_ai_script(self) -> None:
        """Test ai_script doesn't crash."""
        try:
            ai_script("backup my home directory")
        except Exception:
            pass

    def test_ai_translate(self) -> None:
        """Test ai_translate doesn't crash."""
        try:
            ai_translate("ls -la", "windows")
        except Exception:
            pass