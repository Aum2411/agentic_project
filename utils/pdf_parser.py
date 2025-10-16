# utils/pdf_parser.py
from io import BytesIO
try:
    from PyPDF2 import PdfReader
except Exception:
    PdfReader = None

def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Return extracted text from pdf bytes. Raises if PyPDF2 not available."""
    if PdfReader is None:
        raise ImportError("PyPDF2 not installed. Install with `pip install PyPDF2`.")
    reader = PdfReader(BytesIO(pdf_bytes))
    text_parts = []
    for p in reader.pages:
        page_text = p.extract_text() or ""
        text_parts.append(page_text)
    return "\n".join(text_parts)
