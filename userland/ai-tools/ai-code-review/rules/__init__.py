"""Rules package for AI Code Review.

Contains rule modules for security analysis and performance analysis.
"""

from .security_rules import get_all_security_rules
from .performance_rules import get_all_performance_rules

__all__ = [
    "get_all_security_rules",
    "get_all_performance_rules",
]