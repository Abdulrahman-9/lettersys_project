"""
core.extraction.matchers
=========================
Pattern and entity matcher subpackage.

Classes:
  EntityMatcher — from .entity
  PatternMatcher, DateParser — from .pattern
  extract_structured_data — from .pattern
"""

from .entity import EntityMatcher
from .pattern import PatternMatcher, DateParser, extract_structured_data

__all__ = [
    'EntityMatcher',
    'PatternMatcher',
    'DateParser',
    'extract_structured_data',
]
