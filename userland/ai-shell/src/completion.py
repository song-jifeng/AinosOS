"""
AI-driven auto-completion for Ainos Shell.

Provides intelligent completion suggestions using AI:
- Context-aware command completion
- Natural language to command completion
- Learning from user history patterns
- Smart argument completion based on command analysis
- Predictive completion (suggesting next command)
"""

from __future__ import annotations

import os
import re
import typing as t
from dataclasses import dataclass, field
from collections import Counter, defaultdict

from .utils import (
    AnsiCode,
    get_config,
    truncate,
    terminal_width,
    find_executable,
)
from .config import get_aliases
from .history import get_history_manager, HistoryEntry
from .completer import Completion, CompletionResult

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class CompletionPrediction:
    """A predicted completion with score."""
    text: str
    score: float
    source: str  # history, pattern, frequency, ai
    context: str = ""

    def __repr__(self) -> str:
        return f"Prediction({self.text!r}, score={self.score:.2f}, src={self.source})"


# ---------------------------------------------------------------------------
# Frequency-based completion
# ---------------------------------------------------------------------------

class FrequencyAnalyzer:
    """Analyzes command frequency patterns for better completions."""

    def __init__(self) -> None:
        self._command_freq: Counter = Counter()
        self._bigram_freq: Counter = Counter()
        self._trigram_freq: Counter = Counter()
        self._last_commands: t.List[str] = []
        self._loaded = False

    def load(self) -> None:
        """Load frequency data from history."""
        if self._loaded:
            return

        try:
            history = get_history_manager()
            entries = history.get(limit=1000)

            commands = []
            for entry in entries:
                cmd = entry.command.strip()
                if cmd:
                    commands.append(cmd)
                    self._command_freq[cmd] += 1

            # Build n-gram frequencies
            for i in range(len(commands) - 1):
                self._bigram_freq[(commands[i], commands[i + 1])] += 1
            for i in range(len(commands) - 2):
                self._trigram_freq[(commands[i], commands[i + 1], commands[i + 2])] += 1

            self._last_commands = commands[-10:] if len(commands) >= 10 else commands
            self._loaded = True
        except Exception:
            pass

    def get_frequent_commands(self, prefix: str, limit: int = 10) -> t.List[CompletionPrediction]:
        """Get frequently used commands matching the prefix."""
        self.load()
        predictions = []
        for cmd, freq in self._command_freq.most_common(100):
            if cmd.startswith(prefix):
                predictions.append(CompletionPrediction(
                    text=cmd,
                    score=min(1.0, freq / 50),
                    source="frequency",
                ))
        return predictions[:limit]

    def predict_next_command(self, prefix: str = "") -> t.List[CompletionPrediction]:
        """Predict the next command based on bigram/trigram patterns."""
        self.load()
        predictions = []

        if len(self._last_commands) >= 2:
            last_two = (self._last_commands[-2], self._last_commands[-1])
            for (c1, c2, c3), freq in self._trigram_freq.most_common(50):
                if (c1, c2) == last_two and (not prefix or c3.startswith(prefix)):
                    predictions.append(CompletionPrediction(
                        text=c3,
                        score=min(1.0, freq / 10),
                        source="pattern",
                        context=f"after '{c1} {c2}'",
                    ))

        if not predictions and len(self._last_commands) >= 1:
            last_cmd = self._last_commands[-1]
            for (c1, c2), freq in self._bigram_freq.most_common(50):
                if c1 == last_cmd and (not prefix or c2.startswith(prefix)):
                    predictions.append(CompletionPrediction(
                        text=c2,
                        score=min(1.0, freq / 20),
                        source="pattern",
                        context=f"after '{c1}'",
                    ))

        return predictions[:10]

    def get_command_frequency(self, command: str) -> int:
        """Get the frequency of a command."""
        self.load()
        return self._command_freq.get(command, 0)

    def __repr__(self) -> str:
        return f"FrequencyAnalyzer(loaded={self._loaded})"


# ---------------------------------------------------------------------------
# Context-aware completion
# ---------------------------------------------------------------------------

class ContextAnalyzer:
    """Analyzes the current context for better completions."""

    def __init__(self) -> None:
        self._cwd_files: t.List[str] = []
        self._cwd_dirs: t.List[str] = []
        self._last_scan: float = 0
        self._scan_interval = 5.0  # seconds

    def scan_cwd(self) -> None:
        """Scan the current directory for files and dirs."""
        import time
        now = time.time()
        if now - self._last_scan < self._scan_interval:
            return

        self._cwd_files = []
        self._cwd_dirs = []
        try:
            for entry in os.listdir("."):
                if os.path.isdir(entry):
                    self._cwd_dirs.append(entry)
                else:
                    self._cwd_files.append(entry)
        except PermissionError:
            pass
        self._last_scan = now

    def suggest_files(self, prefix: str, limit: int = 10) -> t.List[CompletionPrediction]:
        """Suggest files matching prefix."""
        self.scan_cwd()
        predictions = []
        for f in self._cwd_files:
            if f.startswith(prefix):
                predictions.append(CompletionPrediction(
                    text=f,
                    score=0.8,
                    source="file",
                ))
        return predictions[:limit]

    def suggest_dirs(self, prefix: str, limit: int = 5) -> t.List[CompletionPrediction]:
        """Suggest directories matching prefix."""
        self.scan_cwd()
        predictions = []
        for d in self._cwd_dirs:
            if d.startswith(prefix):
                predictions.append(CompletionPrediction(
                    text=d + "/",
                    score=0.9,
                    source="dir",
                ))
        return predictions[:limit]

    def suggest_for_command(self, command: str, partial: str) -> t.List[CompletionPrediction]:
        """Suggest arguments for a specific command based on context."""
        predictions = []

        # Common patterns
        if command in ("cd", "rmdir", "pushd"):
            predictions.extend(self.suggest_dirs(partial))
        elif command in ("cat", "head", "tail", "less", "more", "nano", "vim"):
            predictions.extend(self.suggest_files(partial))
        elif command in ("ls", "ll", "la"):
            predictions.extend(self.suggest_dirs(partial))
            predictions.extend(self.suggest_files(partial))
        elif command in ("cp", "mv"):
            predictions.extend(self.suggest_files(partial))
            predictions.extend(self.suggest_dirs(partial))
        elif command in ("rm", "rmdir"):
            predictions.extend(self.suggest_files(partial))
        elif command in ("python", "python3", "node", "bash", "sh"):
            predictions.extend(self.suggest_files(partial))

        return predictions

    def __repr__(self) -> str:
        files = len(self._cwd_files)
        dirs = len(self._cwd_dirs)
        return f"ContextAnalyzer(files={files}, dirs={dirs})"


# ---------------------------------------------------------------------------
# AI Completion Engine
# ---------------------------------------------------------------------------

class AICompletionEngine:
    """AI-powered completion engine that combines multiple strategies."""

    def __init__(self) -> None:
        self.frequency = FrequencyAnalyzer()
        self.context = ContextAnalyzer()
        self._predictions: t.List[CompletionPrediction] = []

    def complete(self, text: str, cursor_pos: int) -> CompletionResult:
        """Get AI-enhanced completions for the current input."""
        words = text[:cursor_pos].split()
        if not words:
            return self._complete_first_word("")

        current_word = words[-1] if text[:cursor_pos].endswith(words[-1]) else ""
        is_first = len(words) == 1

        if is_first:
            return self._complete_first_word(current_word)
        else:
            command = words[0]
            args = words[1:-1] if current_word else words[1:]
            return self._complete_arg(command, args, current_word)

    def _complete_first_word(self, prefix: str) -> CompletionResult:
        """Complete the first word (command name)."""
        seen = set()
        result = CompletionResult(prefix=prefix)

        # 1. Frequent commands
        freq_preds = self.frequency.get_frequent_commands(prefix, limit=10)
        for pred in freq_preds:
            if pred.text not in seen:
                seen.add(pred.text)
                result.completions.append(Completion(
                    text=pred.text,
                    type="command",
                    score=pred.score,
                    description=f"freq:{pred.score:.2f}",
                ))

        # 2. Predicted next command
        next_preds = self.frequency.predict_next_command(prefix=prefix)
        for pred in next_preds:
            if pred.text not in seen:
                seen.add(pred.text)
                result.completions.append(Completion(
                    text=pred.text,
                    type="command",
                    score=pred.score * 1.2,  # Boost predictions
                    description=f"predicted:{pred.context}",
                ))

        return result

    def _complete_arg(self, command: str, args: t.List[str],
                      current_word: str) -> CompletionResult:
        """Complete arguments for a command."""
        seen = set()
        result = CompletionResult(prefix=current_word)

        # Context-aware suggestions
        context_preds = self.context.suggest_for_command(command, current_word)
        for pred in context_preds:
            if pred.text not in seen:
                seen.add(pred.text)
                result.completions.append(Completion(
                    text=pred.text,
                    type=pred.source,
                    score=pred.score,
                ))

        return result

    def get_predictive_suggestions(self, num: int = 3) -> t.List[str]:
        """Get predictive suggestions for the next command."""
        predictions = self.frequency.predict_next_command()
        return [p.text for p in predictions[:num]]

    def learn_from_command(self, command: str) -> None:
        """Learn from a command execution."""
        self.frequency._command_freq[command] += 1
        self.frequency._last_commands.append(command)

    def __repr__(self) -> str:
        return f"AICompletionEngine(freq={self.frequency}, ctx={self.context})"


# ---------------------------------------------------------------------------
# Module-level access
# ---------------------------------------------------------------------------

_ai_completion: t.Optional[AICompletionEngine] = None


def get_ai_completion_engine() -> AICompletionEngine:
    """Get the global AI completion engine."""
    global _ai_completion
    if _ai_completion is None:
        _ai_completion = AICompletionEngine()
    return _ai_completion


__all__ = [
    "CompletionPrediction",
    "FrequencyAnalyzer",
    "ContextAnalyzer",
    "AICompletionEngine",
    "get_ai_completion_engine",
]