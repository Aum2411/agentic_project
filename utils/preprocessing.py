# utils/preprocessing.py
import re

def clean_text(text: str, max_chars: int = 15000) -> str:
    if not text:
        return ""
    # Normalize whitespace
    t = re.sub(r"\s+", " ", text).strip()
    # Remove common page footers like "Page 1 of 3"
    t = re.sub(r"Page \d+ of \d+", "", t, flags=re.IGNORECASE)
    if len(t) > max_chars:
        t = t[:max_chars] + "\n... (truncated)"
    return t
