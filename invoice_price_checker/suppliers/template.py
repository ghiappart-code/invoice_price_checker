from __future__ import annotations

from typing import BinaryIO

import pandas as pd

from invoice_price_checker.models import ParsedInvoice
from invoice_price_checker.suppliers.base import SupplierInvoiceParser
from invoice_price_checker.text import extract_pdf_text, parse_decimal


class NewSupplierParser(SupplierInvoiceParser):
    """Copy this file when creating a supplier-specific parser."""

    supplier_code = "NEW_SUPPLIER"
    display_name = "New supplier"

    def parse(self, file: BinaryIO) -> ParsedInvoice:
        text = extract_pdf_text(file)

        records: list[dict[str, object]] = []
        for raw_line in text.splitlines():
            # Replace this block with supplier-specific table extraction rules.
            parts = raw_line.split()
            if len(parts) < 4:
                continue
            unit_price = parse_decimal(parts[-1])
            if unit_price is None:
                continue
            records.append(
                {
                    "supplier_article_code": parts[0],
                    "description": " ".join(parts[1:-2]),
                    "quantity": parse_decimal(parts[-2]),
                    "unit_price": unit_price,
                    "currency": "EUR",
                    "raw_line": raw_line,
                }
            )

        return ParsedInvoice(
            supplier_code=self.supplier_code,
            invoice_number=None,
            invoice_date=None,
            lines=pd.DataFrame(records),
            metadata={"supplier_code": self.supplier_code, "line_count": len(records)},
        )
