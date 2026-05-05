"""Document type defaults and option catalogs per archival kind."""

DOCUMENT_TYPE_OPTIONS_BY_KIND = {
    "incoming_internal": [
        "مذكرة داخلية",
        "اعمام",
        "تقرير",
        "محضر",
        "ايميل",
        "استمارة",
        "امر اداري",
        "امر وزاري",
        "جدول",
        "طلب",
        "مطالعه",
        "ورقة عمل",
    ],
    "incoming_external": [
        "مذكرة خارجية",
        "اعمام",
        "تقرير",
        "محضر",
        "ايميل",
        "استمارة",
        "امر اداري",
        "امر وزاري",
        "جدول",
        "طلب",
        "مطالعه",
        "ورقة عمل",
        "مذكرة داخلية",
    ],
    "outgoing_internal": [
        "مذكرة داخلية",
        "اعمام",
        "تقرير",
        "محضر",
        "ايميل",
        "استمارة",
        "امر اداري",
        "امر وزاري",
        "جدول",
        "طلب",
        "مطالعه",
        "ورقة عمل",
    ],
    "outgoing_external": [
        "مذكرة خارجية",
        "اعمام",
        "تقرير",
        "محضر",
        "ايميل",
        "استمارة",
        "امر اداري",
        "امر وزاري",
        "جدول",
        "طلب",
        "مطالعه",
        "ورقة عمل",
        "مذكرة داخلية",
    ],
}

DEFAULT_DOCUMENT_TYPE_BY_KIND = {
    kind: options[0]
    for kind, options in DOCUMENT_TYPE_OPTIONS_BY_KIND.items()
    if options
}

ALL_DOCUMENT_TYPES = tuple(
    dict.fromkeys(
        item
        for options in DOCUMENT_TYPE_OPTIONS_BY_KIND.values()
        for item in options
    )
)


def normalize_document_type_value(value):
    """Trim and collapse whitespace inside document-type labels."""
    return " ".join(str(value or "").split())


def get_document_type_options(kind=None):
    if kind is None:
        return list(ALL_DOCUMENT_TYPES)
    return list(
        DOCUMENT_TYPE_OPTIONS_BY_KIND.get(
            kind,
            DOCUMENT_TYPE_OPTIONS_BY_KIND["incoming_internal"],
        )
    )


def get_default_document_type(kind):
    return DEFAULT_DOCUMENT_TYPE_BY_KIND.get(
        kind,
        DEFAULT_DOCUMENT_TYPE_BY_KIND["incoming_internal"],
    )


def resolve_document_type(kind, value):
    normalized = normalize_document_type_value(value)
    return normalized or get_default_document_type(kind)