from __future__ import annotations

import re
import unicodedata

from invoice_price_checker.suppliers.agidra import AgidraParser
from invoice_price_checker.suppliers.base import SupplierInvoiceParser
from invoice_price_checker.suppliers.dds import DdsParser
from invoice_price_checker.suppliers.ekibio import EkibioParser
from invoice_price_checker.suppliers.epice import EpiceParser
from invoice_price_checker.suppliers.generic import GenericSupplierParser
from invoice_price_checker.suppliers.halle_bio_occitanie import HalleBioOccitanieParser
from invoice_price_checker.suppliers.relais_vert import RelaisVertParser


_PARSERS: dict[str, type[SupplierInvoiceParser]] = {
    AgidraParser.supplier_code: AgidraParser,
    DdsParser.supplier_code: DdsParser,
    GenericSupplierParser.supplier_code: GenericSupplierParser,
    EkibioParser.supplier_code: EkibioParser,
    EpiceParser.supplier_code: EpiceParser,
    HalleBioOccitanieParser.supplier_code: HalleBioOccitanieParser,
    RelaisVertParser.supplier_code: RelaisVertParser,
}

_DETECTION_KEYWORDS: dict[str, tuple[str, ...]] = {
    AgidraParser.supplier_code: ("agidra",),
    DdsParser.supplier_code: ("ysbonfacpdds", "dds"),
    EkibioParser.supplier_code: ("ekibio",),
    EpiceParser.supplier_code: ("epice",),
    HalleBioOccitanieParser.supplier_code: ("halle bio occitanie", "halle bio"),
    RelaisVertParser.supplier_code: ("relais-vert.com", "relais vert"),
}

_SUPPLIER_DETECTION_HEADER_CHARS = 1200


def list_suppliers(include_generic: bool = True) -> list[str]:
    supplier_codes = sorted(_PARSERS)
    if include_generic:
        return supplier_codes
    return [code for code in supplier_codes if code != GenericSupplierParser.supplier_code]


def supplier_label(supplier_code: str) -> str:
    parser_class = _PARSERS.get(supplier_code)
    if parser_class is None:
        return supplier_code
    return f"{parser_class.display_name} ({supplier_code})"


def get_parser(supplier_code: str) -> SupplierInvoiceParser:
    try:
        return _PARSERS[supplier_code]()
    except KeyError as exc:
        raise ValueError(f"Unknown supplier parser: {supplier_code}") from exc


def detect_supplier_from_text(text: str) -> str | None:
    text_key = _supplier_detection_key(text[:_SUPPLIER_DETECTION_HEADER_CHARS])
    for supplier_code, keywords in _DETECTION_KEYWORDS.items():
        if any(_has_supplier_keyword(text_key, keyword) for keyword in keywords):
            return supplier_code
    return None


def _has_supplier_keyword(text_key: str, keyword: str) -> bool:
    keyword_key = _supplier_detection_key(keyword)
    return bool(re.search(rf"\b{re.escape(keyword_key)}\b", text_key))


def _supplier_detection_key(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold()
    return re.sub(r"[^a-z0-9]+", " ", text)
