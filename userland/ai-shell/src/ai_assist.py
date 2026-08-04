"""
AI assistant module for Ainos Shell.

Provides AI-powered features:
- Natural language to command translation
- Error explanation and debugging suggestions
- Command suggestions and recommendations
- Context-aware completions
- Command optimization suggestions
- Learning from user behavior
- Multi-provider support (OpenAI, Anthropic, local models)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
import typing as t
from dataclasses import dataclass, field
from datetime import datetime

from .utils import (
    AnsiCode,
    colorize,
    ShellError,
    get_env,
    truncate,
    terminal_width,
)
from .config import get_config

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class AICommand:
    """An AI-generated command suggestion."""
    command: str = ""
    description: str = ""
    confidence: float = 0.0
    needs_confirmation: bool = True
    explanation: str = ""

    def __repr__(self) -> str:
        return f"AICommand({self.command!r}, conf={self.confidence:.2f})"


@dataclass
class AIErrorExplanation:
    """An explanation for a command error."""
    error_text: str = ""
    explanation: str = ""
    suggestions: list = field(default_factory=list)
    fix_command: str = ""

    def __repr__(self) -> str:
        return f"AIErrorExplanation(suggestions={len(self.suggestions)})"


@dataclass
class AISuggestion:
    """A general AI suggestion."""
    text: str = ""
    category: str = "general"  # general, optimization, tip, warning
    priority: int = 0  # 0-10, higher = more important
    source: str = "ai"

    def __repr__(self) -> str:
        return f"AISuggestion({self.text!r}, cat={self.category})"


# ---------------------------------------------------------------------------
# Provider interface
# ---------------------------------------------------------------------------

class AIProvider:
    """Abstract base class for AI providers."""

    def __init__(self, config: t.Optional[dict] = None) -> None:
        self.config = config or {}

    def generate(self, prompt: str, system_prompt: str = "",
                 max_tokens: int = 256, temperature: float = 0.3) -> str:
        """Generate a response from the AI model."""
        raise NotImplementedError

    def supports_streaming(self) -> bool:
        """Whether this provider supports streaming responses."""
        return False

    def name(self) -> str:
        """Get the provider name."""
        return "base"


class OpenAIProvider(AIProvider):
    """OpenAI API provider."""

    def __init__(self, config: t.Optional[dict] = None) -> None:
        super().__init__(config)
        self.api_key = self.config.get("api_key", get_env("OPENAI_API_KEY", ""))
        self.model = self.config.get("model", "gpt-4o")
        self.api_base = self.config.get("api_base", "https://api.openai.com/v1")
        self.timeout = self.config.get("timeout", 30)

    def generate(self, prompt: str, system_prompt: str = "",
                 max_tokens: int = 256, temperature: float = 0.3) -> str:
        if not self.api_key:
            return ""

        try:
            import httpx
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            data = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt or "You are a helpful shell assistant."},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": max_tokens,
                "temperature": temperature,
            }

            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    f"{self.api_base}/chat/completions",
                    headers=headers,
                    json=data,
                )
                response.raise_for_status()
                result = response.json()
                return result["choices"][0]["message"]["content"].strip()
        except Exception as e:
            return f""

    def name(self) -> str:
        return f"openai/{self.model}"


class AnthropicProvider(AIProvider):
    """Anthropic API provider."""

    def __init__(self, config: t.Optional[dict] = None) -> None:
        super().__init__(config)
        self.api_key = self.config.get("api_key", get_env("ANTHROPIC_API_KEY", ""))
        self.model = self.config.get("model", "claude-sonnet-4-20250514")
        self.api_base = self.config.get("api_base", "https://api.anthropic.com/v1")
        self.timeout = self.config.get("timeout", 30)

    def generate(self, prompt: str, system_prompt: str = "",
                 max_tokens: int = 256, temperature: float = 0.3) -> str:
        if not self.api_key:
            return ""

        try:
            import httpx
            headers = {
                "x-api-key": self.api_key,
                "Content-Type": "application/json",
                "anthropic-version": "2023-06-01",
            }
            data = {
                "model": self.model,
                "system": system_prompt or "You are a helpful shell assistant.",
                "messages": [
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": max_tokens,
                "temperature": temperature,
            }

            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    f"{self.api_base}/messages",
                    headers=headers,
                    json=data,
                )
                response.raise_for_status()
                result = response.json()
                return result["content"][0]["text"].strip()
        except Exception as e:
            return f""

    def name(self) -> str:
        return f"anthropic/{self.model}"


class LocalProvider(AIProvider):
    """Local model provider (e.g., llama.cpp, ollama)."""

    def __init__(self, config: t.Optional[dict] = None) -> None:
        super().__init__(config)
        self.model_path = self.config.get("local_model_path", "")
        self.endpoint = self.config.get("custom_endpoint", "http://localhost:8080")

    def generate(self, prompt: str, system_prompt: str = "",
                 max_tokens: int = 256, temperature: float = 0.3) -> str:
        # Try Ollama first
        try:
            import httpx
            data = {
                "model": self.config.get("model", "llama3"),
                "prompt": f"{system_prompt}\n\n{prompt}",
                "stream": False,
                "options": {
                    "num_predict": max_tokens,
                    "temperature": temperature,
                },
            }
            with httpx.Client(timeout=30) as client:
                response = client.post(
                    f"{self.endpoint}/api/generate",
                    json=data,
                )
                response.raise_for_status()
                return response.json().get("response", "").strip()
        except Exception:
            pass

        return ""

    def name(self) -> str:
        return f"local/{self.config.get('model', 'unknown')}"


# ---------------------------------------------------------------------------
# AI Assistant
# ---------------------------------------------------------------------------

class AIAssistant:
    """Main AI assistant for the shell."""

    def __init__(self, config: t.Optional[dict] = None) -> None:
        self.config = config or {}
        self._provider: t.Optional[AIProvider] = None
        self._conversation_history: t.List[dict] = []
        self._max_history = 20
        self._initialized = False

    def initialize(self) -> None:
        """Initialize the AI provider."""
        if self._initialized:
            return

        provider_name = self.config.get("provider", "openai")
        if provider_name == "openai":
            self._provider = OpenAIProvider(self.config)
        elif provider_name == "anthropic":
            self._provider = AnthropicProvider(self.config)
        elif provider_name == "local":
            self._provider = LocalProvider(self.config)
        else:
            self._provider = OpenAIProvider(self.config)

        self._initialized = True

    @property
    def provider(self) -> t.Optional[AIProvider]:
        """Get the AI provider (lazy init)."""
        if not self._initialized:
            self.initialize()
        return self._provider

    @property
    def is_available(self) -> bool:
        """Check if the AI provider is configured and available."""
        if not self.config.get("enabled", True):
            return False
        provider = self.provider
        if provider is None:
            return False
        if isinstance(provider, OpenAIProvider):
            return bool(provider.api_key)
        if isinstance(provider, AnthropicProvider):
            return bool(provider.api_key)
        if isinstance(provider, LocalProvider):
            return bool(provider.endpoint)
        return False

    def natural_language_to_command(self, query: str, context: t.Optional[dict] = None) -> t.Optional[AICommand]:
        """Convert natural language to a shell command."""
        if not self.is_available:
            return None

        system_prompt = (
            "You are a shell command expert. Convert natural language requests into shell commands. "
            "Respond with ONLY a JSON object containing: "
            '{"command": "the shell command", "description": "brief description", '
            '"confidence": 0.0-1.0, "explanation": "why this command works"}'
        )

        prompt = f"Convert this request to a shell command: {query}\n"

        if context:
            prompt += f"\nContext:\n"
            prompt += f"Current directory: {context.get('cwd', '')}\n"
            prompt += f"OS: {context.get('os', '')}\n"

        try:
            response = self.provider.generate(
                prompt=prompt,
                system_prompt=system_prompt,
                max_tokens=300,
                temperature=0.2,
            )

            # Parse JSON response
            response = response.strip()
            if response.startswith("```"):
                # Remove code block markers
                lines = response.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                response = "\n".join(lines)

            result = json.loads(response)
            return AICommand(
                command=result.get("command", ""),
                description=result.get("description", ""),
                confidence=result.get("confidence", 0.5),
                explanation=result.get("explanation", ""),
            )
        except (json.JSONDecodeError, Exception) as e:
            # Fallback: try to extract command from plain text
            return self._extract_command_from_text(response)

    def _extract_command_from_text(self, text: str) -> t.Optional[AICommand]:
        """Extract a command from free-form text response."""
        # Try to find code blocks
        code_blocks = re.findall(r"```(?:bash|sh|shell)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if code_blocks:
            cmd = code_blocks[0].strip().split("\n")[0]
            return AICommand(
                command=cmd,
                description="Extracted from AI response",
                confidence=0.6,
                explanation=text[:200],
            )

        # Try to find lines starting with $ or >
        for line in text.split("\n"):
            line = line.strip()
            if line.startswith("$ "):
                return AICommand(
                    command=line[2:],
                    description="Extracted from AI response",
                    confidence=0.5,
                    explanation=text[:200],
                )

        return None

    def explain_error(self, command: str, error_message: str,
                      exit_code: int, cwd: str = "") -> t.Optional[AIErrorExplanation]:
        """Explain a command error and suggest fixes."""
        if not self.is_available:
            return None

        system_prompt = (
            "You are a shell debugging expert. Explain command errors and suggest fixes. "
            "Respond with a JSON object: "
            '{"explanation": "what went wrong", "suggestions": ["fix 1", "fix 2"], '
            '"fix_command": "a corrected command if applicable"}'
        )

        prompt = (
            f"Command: {command}\n"
            f"Error: {error_message}\n"
            f"Exit code: {exit_code}\n"
            f"Directory: {cwd}\n"
            f"Explain this error and suggest fixes."
        )

        try:
            response = self.provider.generate(
                prompt=prompt,
                system_prompt=system_prompt,
                max_tokens=300,
                temperature=0.3,
            )

            response = response.strip()
            if response.startswith("```"):
                lines = response.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                response = "\n".join(lines)

            result = json.loads(response)
            return AIErrorExplanation(
                error_text=error_message,
                explanation=result.get("explanation", ""),
                suggestions=result.get("suggestions", []),
                fix_command=result.get("fix_command", ""),
            )
        except Exception:
            return None

    def suggest_command(self, context: dict) -> t.Optional[AICommand]:
        """Suggest a command based on context."""
        if not self.is_available:
            return None

        cwd = context.get("cwd", "")
        recent_commands = context.get("recent_commands", [])

        system_prompt = (
            "You are a helpful shell assistant. Suggest a useful command based on the current context. "
            "Respond with a JSON object: "
            '{"command": "the command", "description": "what it does", "confidence": 0.0-1.0}'
        )

        prompt = f"Current directory: {cwd}\n"
        if recent_commands:
            prompt += f"Recent commands: {', '.join(recent_commands[-5:])}\n"
        prompt += "Suggest a useful command."

        try:
            response = self.provider.generate(
                prompt=prompt,
                system_prompt=system_prompt,
                max_tokens=200,
                temperature=0.4,
            )

            response = response.strip()
            if response.startswith("```"):
                lines = response.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                response = "\n".join(lines)

            result = json.loads(response)
            return AICommand(
                command=result.get("command", ""),
                description=result.get("description", ""),
                confidence=result.get("confidence", 0.5),
            )
        except Exception:
            return None

    def get_suggestions(self, input_text: str, context: t.Optional[dict] = None) -> t.List[AISuggestion]:
        """Get general suggestions for the current input."""
        if not self.is_available or not input_text:
            return []

        # Simple pattern-based suggestions (no API call needed)
        suggestions = []

        # Check for common patterns
        if input_text.startswith("git "):
            suggestions.extend(self._get_git_suggestions(input_text))
        elif input_text.startswith("docker "):
            suggestions.extend(self._get_docker_suggestions(input_text))
        elif input_text.startswith("pip "):
            suggestions.extend(self._get_pip_suggestions(input_text))

        # Check for common errors
        if "rm -rf" in input_text and "/" in input_text:
            suggestions.append(AISuggestion(
                text="Be careful with rm -rf! Check the path before running.",
                category="warning",
                priority=8,
            ))

        if "|" in input_text and "grep" not in input_text:
            suggestions.append(AISuggestion(
                text="Consider piping to `grep` for filtering output.",
                category="tip",
                priority=2,
            ))

        if "chmod 777" in input_text:
            suggestions.append(AISuggestion(
                text="chmod 777 is very permissive. Consider using more restrictive permissions.",
                category="warning",
                priority=7,
            ))

        return suggestions

    def _get_git_suggestions(self, input_text: str) -> t.List[AISuggestion]:
        """Get git-related suggestions."""
        suggestions = []
        if "commit" in input_text and "-m" not in input_text:
            suggestions.append(AISuggestion(
                text="Use `git commit -m \"message\"` for inline commit messages.",
                category="tip",
                priority=3,
            ))
        if "push" in input_text and not re.search(r"origin\s+\w+", input_text):
            suggestions.append(AISuggestion(
                text="Specify remote and branch: `git push origin main`",
                category="tip",
                priority=2,
            ))
        return suggestions

    def _get_docker_suggestions(self, input_text: str) -> t.List[AISuggestion]:
        """Get docker-related suggestions."""
        suggestions = []
        if "ps" in input_text:
            suggestions.append(AISuggestion(
                text="Use `docker ps -a` to see all containers, including stopped ones.",
                category="tip",
                priority=2,
            ))
        if "rmi" in input_text:
            suggestions.append(AISuggestion(
                text="Use `docker image prune` to clean up unused images.",
                category="tip",
                priority=3,
            ))
        return suggestions

    def _get_pip_suggestions(self, input_text: str) -> t.List[AISuggestion]:
        """Get pip-related suggestions."""
        suggestions = []
        if "install" in input_text:
            suggestions.append(AISuggestion(
                text="Consider using a virtual environment: `python -m venv venv`",
                category="tip",
                priority=4,
            ))
        if "freeze" in input_text:
            suggestions.append(AISuggestion(
                text="Use `pip freeze > requirements.txt` to save dependencies.",
                category="tip",
                priority=2,
            ))
        return suggestions

    def optimize_command(self, command: str) -> t.Optional[str]:
        """Suggest an optimized version of a command."""
        if not self.is_available:
            return None

        # Simple pattern-based optimizations (no API call)
        optimizations = {
            "find . -name . -print": "find . -name '*.py'",
            "grep -r": "grep -rn",
            "ps -ef | grep": "pgrep -f",
            "cat file | grep": "grep pattern file",
            "cat file | head": "head file",
            "cat file | tail": "tail file",
            "cat file | wc -l": "wc -l file",
            "cat file | sort": "sort file",
            "cat file | uniq": "sort -u file",
        }

        for pattern, optimized in optimizations.items():
            if command.strip() == pattern:
                return optimized

        # Check for useless use of cat
        if re.match(r"cat\s+\S+\s*\|\s*", command):
            return None

        return None

    def add_to_history(self, query: str, response: str) -> None:
        """Add a query/response to conversation history."""
        self._conversation_history.append({
            "query": query,
            "response": response,
            "timestamp": datetime.now().isoformat(),
        })
        if len(self._conversation_history) > self._max_history:
            self._conversation_history = self._conversation_history[-self._max_history:]

    def clear_history(self) -> None:
        """Clear conversation history."""
        self._conversation_history.clear()

    def get_status_string(self) -> str:
        """Get a status string for the prompt."""
        if not self.config.get("enabled", True):
            return "AI:off"
        if self.is_available:
            return "AI:on"
        return "AI:no-key"

    def __repr__(self) -> str:
        return f"AIAssistant(available={self.is_available})"


# ---------------------------------------------------------------------------
# Module-level access
# ---------------------------------------------------------------------------

_ai_assistant: t.Optional[AIAssistant] = None


def get_ai_assistant() -> AIAssistant:
    """Get the global AI assistant singleton."""
    global _ai_assistant
    if _ai_assistant is None:
        config = get_config()
        ai_config = {
            "enabled": config.ai.enabled,
            "provider": config.ai.provider,
            "model": config.ai.model,
            "api_key": config.ai.api_key,
            "api_base": config.ai.api_base,
            "temperature": config.ai.temperature,
            "max_tokens": config.ai.max_tokens,
            "timeout": config.ai.timeout,
            "local_model_path": config.ai.local_model_path,
            "custom_endpoint": config.ai.custom_endpoint,
        }
        _ai_assistant = AIAssistant(ai_config)
    return _ai_assistant


def natural_to_command(query: str) -> t.Optional[AICommand]:
    """Convert natural language to a command (convenience function)."""
    return get_ai_assistant().natural_language_to_command(query)


def explain_error(command: str, error: str, exit_code: int) -> t.Optional[AIErrorExplanation]:
    """Explain a command error (convenience function)."""
    return get_ai_assistant().explain_error(command, error, exit_code)


__all__ = [
    "AICommand",
    "AIErrorExplanation",
    "AISuggestion",
    "AIProvider",
    "OpenAIProvider",
    "AnthropicProvider",
    "LocalProvider",
    "AIAssistant",
    "get_ai_assistant",
    "natural_to_command",
    "explain_error",
]