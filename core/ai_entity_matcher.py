# -*- coding: utf-8 -*-
"""ai_entity_matcher.py — SHIM — الكود انتقل إلى core.extraction.matchers.entity"""
from core.extraction.matchers.entity import *  # noqa: F401, F403
from core.extraction.matchers.entity import (
    EntityMatcher,
    NERService,
    EnhancedEntityMatcher,
    match_entity,
    extract_ner_entities,
    smart_entity_match,
)
