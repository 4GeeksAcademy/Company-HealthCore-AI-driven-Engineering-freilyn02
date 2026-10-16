"""PDF -> Markdown conversion (runs BEFORE any agent reads the document).

Agents never see raw PDF bytes: the Markdown is cheaper in tokens and has
less noise.

HIPAA / UK GDPR: converting does NOT write anything to disk. The Markdown
artifact is written only AFTER the PHI guard has redacted the text
(see phi.py and graph.py), so no patient data ever lands in a .md file.
"""
from pathlib import Path

from markitdown import MarkItDown

RAW_RFP_DIR = Path(__file__).resolve().parents[2] / "raw" / "rfp"
MIN_MARKDOWN_CHARS = 200  # below this the PDF is almost surely scanned/empty


class ConversionError(Exception):
    """Raised when a PDF cannot be turned into usable Markdown."""


def pdf_to_markdown(pdf_path: str | Path) -> str:
    """Converts a PDF and returns the Markdown text (nothing is written)."""
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise ConversionError(f"PDF not found: {pdf_path}")

    try:
        result = MarkItDown().convert(str(pdf_path))
    except Exception as exc:  # MarkItDown raises many different exception types
        raise ConversionError(f"MarkItDown failed: {exc}") from exc

    text = (result.text_content or "").strip()
    if len(text) < MIN_MARKDOWN_CHARS:
        raise ConversionError(
            "Converted document has almost no text (scanned PDF or empty file)."
        )
    return text


def write_markdown(pdf_path: str | Path, text: str) -> Path:
    """Writes <same name>.md next to the PDF. Call it ONLY with redacted text."""
    md_path = Path(pdf_path).with_suffix(".md")
    md_path.write_text(text, encoding="utf-8")
    return md_path
