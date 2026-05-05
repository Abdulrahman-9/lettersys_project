"""
core.extraction.matchers
=========================
Pattern and entity matcher subpackage.

Classes:
  EntityMatcher, NERService, EnhancedEntityMatcher — from .entity
  PatternMatcher, DateParser — from .pattern
  extract_structured_data — from .pattern
"""

from .entity import EntityMatcher, NERService, EnhancedEntityMatcher
from .pattern import PatternMatcher, DateParser, extract_structured_data

__all__ = [
    'EntityMatcher',
    'NERService',
    'EnhancedEntityMatcher',
    'PatternMatcher',
    'DateParser',
    'extract_structured_data',
]
