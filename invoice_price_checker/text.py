from __future__ import annotations

import re
import unicodedata
from typing import BinaryIO


def normalize_key(value: object) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold()
    return re.sub(r"[^a-z0-9]+", "", text)


def parse_decimal(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = re.sub(r"[^0-9,.\-]", "", text)
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def extract_pdf_text(file: BinaryIO) -> str:
    try:
        import fitz

        file.seek(0)
        data = file.read()
        with fitz.open(stream=data, filetype="pdf") as doc:
            return "\n".join(page.get_text() for page in doc)
    except Exception:
        pass

    try:
        import pdfplumber

        file.seek(0)
        with pdfplumber.open(file) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages)
    except Exception:
        from pypdf import PdfReader

        file.seek(0)
        reader = PdfReader(file)
        return "\n".join(page.extract_text() or "" for page in reader.pages)
