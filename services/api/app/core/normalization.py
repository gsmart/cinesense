import re
import unicodedata

SPACE_RE = re.compile(r"\s+")
PUNCT_RE = re.compile(r"[^a-z0-9\s]")


def normalize_title(value: str) -> str:
    text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    text = text.lower().strip()
    text = PUNCT_RE.sub(" ", text)
    return SPACE_RE.sub(" ", text).strip()


def normalize_region(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip().upper()
    return cleaned or None
