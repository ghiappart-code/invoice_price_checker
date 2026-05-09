from __future__ import annotations

from invoice_price_checker.suppliers.agidra import AgidraParser
from invoice_price_checker.suppliers.base import SupplierInvoiceParser
from invoice_price_checker.suppliers.ekibio import EkibioParser
from invoice_price_checker.suppliers.epice import EpiceParser
from invoice_price_checker.suppliers.generic import GenericSupplierParser
from invoice_price_checker.suppliers.halle_bio_occitanie import HalleBioOccitanieParser
from invoice_price_checker.suppliers.relais_vert import RelaisVertParser


_PARSERS: dict[str, type[SupplierInvoiceParser]] = {
    AgidraParser.supplier_code: AgidraParser,
    GenericSupplierParser.supplier_code: GenericSupplierParser,
    EkibioParser.supplier_code: EkibioParser,
    EpiceParser.supplier_code: EpiceParser,
    HalleBioOccitanieParser.supplier_code: HalleBioOccitanieParser,
    RelaisVertParser.supplier_code: RelaisVertParser,
}


def list_suppliers() -> list[str]:
    return sorted(_PARSERS)


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
