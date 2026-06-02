"""
skills/pdf_reader.py

Extracts text from PDF files using pdfplumber.
Used by Map Extraction Agent (textbook chapters)
and kb_access (curriculum docs that are PDFs).
"""

import pdfplumber
from skills.file_io import file_exists


def extract_text_from_pdf(path: str) -> str:
    """
    Extract all text from a PDF file, page by page.

    Args:
        path: Absolute path to the PDF file.

    Returns:
        Full extracted text as a single string.
        Pages are separated by a newline.

    Raises:
        FileNotFoundError: If the PDF does not exist.
        ValueError: If the PDF is empty or unreadable.
    """
    if not file_exists(path):
        raise FileNotFoundError(f"PDF not found: {path}")

    pages = []
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text()
            if text:
                pages.append(text.strip())

    if not pages:
        raise ValueError(f"No extractable text found in PDF: {path}")

    return "\n\n".join(pages)


def extract_text_from_pdf_by_page(path: str) -> list[str]:
    """
    Extract text from a PDF file, returning a list with one entry per page.
    Useful when page structure matters (e.g. for chunking large textbooks).

    Args:
        path: Absolute path to the PDF file.

    Returns:
        List of strings, one per page. Empty pages are excluded.

    Raises:
        FileNotFoundError: If the PDF does not exist.
        ValueError: If the PDF is empty or unreadable.
    """
    if not file_exists(path):
        raise FileNotFoundError(f"PDF not found: {path}")

    pages = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text and text.strip():
                pages.append(text.strip())

    if not pages:
        raise ValueError(f"No extractable text found in PDF: {path}")

    return pages
