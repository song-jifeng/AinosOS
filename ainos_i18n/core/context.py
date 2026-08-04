"""
Context-Aware Translation
=========================

Provides disambiguation for translation keys that have different meanings
depending on context.  For example, the English word "run" could be translated
differently in Chinese depending on whether it's a verb (跑步) or a noun (运行).

This module supports:

* Context-scoped translation lookups
* Context stack for nested context resolution
* Mapped context translations
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ContextTranslator:
    """Context-aware translation disambiguation.

    Allows translation keys to be scoped by a context string, enabling
    different translations for the same key depending on usage context.

    Parameters
    ----------
    translator : Translator, optional
        Reference to the parent translator (set after construction).
    """

    def __init__(self, translator: Any | None = None) -> None:
        self._translator = translator
        self._context_stack: list[str] = []
        self._context_map: dict[str, dict[str, str]] = {}  # context -> key -> translation

    # ---- Context management ----

    def set_context(self, context: str) -> "ContextTranslator":
        """Set the current translation context.

        Parameters
        ----------
        context : str
            Context identifier, e.g. ``"button"``, ``"menu"``, ``"tooltip"``.

        Returns
        -------
        ContextTranslator
            Self for chaining.
        """
        if self._context_stack:
            self._context_stack[-1] = context
        else:
            self._context_stack.append(context)
        logger.debug("Context set to: %s", context)
        return self

    def push_context(self, context: str) -> "ContextTranslator":
        """Push a context onto the stack.

        Parameters
        ----------
        context : str
            Context identifier.

        Returns
        -------
        ContextTranslator
        """
        self._context_stack.append(context)
        return self

    def pop_context(self) -> str | None:
        """Pop the current context from the stack.

        Returns
        -------
        str | None
            The removed context, or None if stack is empty.
        """
        if self._context_stack:
            return self._context_stack.pop()
        return None

    @property
    def current_context(self) -> str | None:
        """Get the current context without popping."""
        if self._context_stack:
            return self._context_stack[-1]
        return None

    def clear_context(self) -> None:
        """Clear all contexts from the stack."""
        self._context_stack.clear()

    # ---- Context translation ----

    def with_context(self, context: str) -> "ContextTranslator":
        """Create a new context-bound translator.

        This creates a shallow copy of the context translator with the
        given context pushed onto its stack.

        Parameters
        ----------
        context : str
            Context identifier.

        Returns
        -------
        ContextTranslator
        """
        new_ct = ContextTranslator(self._translator)
        # Copy existing context stack
        new_ct._context_stack = list(self._context_stack)
        new_ct._context_map = self._context_map
        new_ct.push_context(context)
        return new_ct

    def t(self, key: str, *args: object, **kwargs: object) -> str:
        """Translate a key with the current context.

        Parameters
        ----------
        key : str
            Translation key.
        *args : object
            Positional format arguments.
        **kwargs : object
            Named format arguments, plus optional ``locale``, ``count``, ``default``.

        Returns
        -------
        str
        """
        context = self.current_context
        locale = kwargs.pop("locale", None)
        count = kwargs.pop("count", None)
        default = kwargs.pop("default", None)

        if self._translator is not None:
            return self._translator.translate(
                key,
                *args,
                locale=locale,
                count=count,
                context=context,
                default=default,
                **kwargs,
            )

        # Fallback: direct context map lookup
        if context and context in self._context_map:
            ctx_keys = self._context_map[context]
            if key in ctx_keys:
                return ctx_keys[key]

        return default or key

    def register_context_translation(
        self,
        context: str,
        key: str,
        translation: str,
    ) -> None:
        """Register a context-specific translation mapping.

        Parameters
        ----------
        context : str
            Context identifier.
        key : str
            Translation key.
        translation : str
            Context-specific translation.
        """
        if context not in self._context_map:
            self._context_map[context] = {}
        self._context_map[context][key] = translation
        logger.debug("Registered context translation: %s / %s -> %s", context, key, translation)

    def register_context_translations(
        self,
        context: str,
        mappings: dict[str, str],
    ) -> None:
        """Register multiple context-specific translations.

        Parameters
        ----------
        context : str
            Context identifier.
        mappings : dict[str, str]
            Key -> translation mappings.
        """
        for key, translation in mappings.items():
            self.register_context_translation(context, key, translation)

    def get_context_keys(self, context: str) -> dict[str, str]:
        """Get all registered translations for a context.

        Parameters
        ----------
        context : str
            Context identifier.

        Returns
        -------
        dict[str, str]
        """
        return dict(self._context_map.get(context, {}))

    def has_context(self, context: str) -> bool:
        """Check if a context has any registered translations.

        Parameters
        ----------
        context : str
            Context identifier.

        Returns
        -------
        bool
        """
        return context in self._context_map and bool(self._context_map[context])

    # ---- Context groups ----

    def register_context_group(
        self,
        group_name: str,
        contexts: list[str],
        translations: dict[str, dict[str, str]],
    ) -> None:
        """Register a group of related contexts.

        Parameters
        ----------
        group_name : str
            Name for the context group.
        contexts : list[str]
            List of context identifiers.
        translations : dict[str, dict[str, str]]
            Mapping of context -> key -> translation.
        """
        for ctx in contexts:
            if ctx in translations:
                self.register_context_translations(ctx, translations[ctx])

    def __repr__(self) -> str:
        stack = self._context_stack
        return (
            f"ContextTranslator(stack={stack}, "
            f"registered_contexts={list(self._context_map.keys())})"
        )