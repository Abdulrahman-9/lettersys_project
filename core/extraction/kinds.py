"""Shared book-kind constants and helpers for extraction and book workflows."""

DEFAULT_BOOK_KIND = "incoming_internal"

BOOK_KIND_CHOICES = (
    ("outgoing_internal", "صادر داخلي"),
    ("outgoing_external", "صادر خارجي"),
    ("incoming_internal", "وارد داخلي"),
    ("incoming_external", "وارد خارجي"),
)

BOOK_KIND_LABELS = dict(BOOK_KIND_CHOICES)

LEGACY_KIND_MAP = {
    "incoming": "incoming_internal",
    "outgoing": "outgoing_internal",
}

DIRECTION_LABELS = {
    "incoming": "وارد عام",
    "outgoing": "صادر عام",
}

EXTRACTION_KIND_CHOICES = (
    ("incoming", "وارد عام"),
    ("outgoing", "صادر عام"),
    *BOOK_KIND_CHOICES,
)


def normalize_book_kind(value, default=DEFAULT_BOOK_KIND):
    lowered = (value or "").strip().lower()
    if not lowered:
        return default
    if lowered in LEGACY_KIND_MAP:
        return LEGACY_KIND_MAP[lowered]
    if lowered in BOOK_KIND_LABELS:
        return lowered
    return default


def is_incoming_kind(value):
    normalized = normalize_book_kind(value, default=None)
    return bool(normalized and normalized.startswith("incoming"))


def is_outgoing_kind(value):
    normalized = normalize_book_kind(value, default=None)
    return bool(normalized and normalized.startswith("outgoing"))


def get_kind_direction(value, default="incoming"):
    normalized = normalize_book_kind(value, default=None)
    if normalized:
        return "incoming" if normalized.startswith("incoming") else "outgoing"
    lowered = (value or "").strip().lower()
    if lowered in ("incoming", "outgoing"):
        return lowered
    return default


def get_kind_scope(value, default="internal"):
    normalized = normalize_book_kind(value, default=None)
    if normalized:
        return "internal" if normalized.endswith("internal") else "external"
    return default


def get_kind_label(value):
    lowered = (value or "").strip().lower()
    if lowered in BOOK_KIND_LABELS:
        return BOOK_KIND_LABELS[lowered]
    normalized = normalize_book_kind(lowered, default=None)
    if normalized:
        return BOOK_KIND_LABELS[normalized]
    return DIRECTION_LABELS.get(lowered, "غير محدد")
