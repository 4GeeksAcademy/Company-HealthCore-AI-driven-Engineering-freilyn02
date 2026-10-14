"""PDF -> Markdown conversion (runs BEFORE any agent reads the document).

Agents never see raw PDF bytes: the Markdown is cheaper in tokens and has
less noise. The .md artifact is saved next to the PDF under data/raw/rfp/.
"""
from pathlib import Path

from markitdown import MarkItDown

RAW_RFP_DIR = Path(__file__).resolve().parents[2] / "raw" / "rfp"
MIN_MARKDOWN_CHARS = 200  # below this the PDF is almost surely scanned/empty


class ConversionError(Exception):
    """Raised when a PDF cannot be turned into usable Markdown."""


def pdf_to_markdown(pdf_path: str | Path) -> tuple[str, Path]:
    """Converts a PDF and writes <same name>.md next to it.

    Returns (markdown_text, markdown_path). Raises ConversionError instead of
    returning empty text, so the ticket never fails silently.
    """
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

    md_path = pdf_path.with_suffix(".md")
    md_path.write_text(text, encoding="utf-8")
    return text, md_path
