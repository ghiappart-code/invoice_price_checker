from __future__ import annotations

import re
from datetime import date
from typing import BinaryIO

import pandas as pd

from invoice_price_checker.models import ParsedInvoice
from invoice_price_checker.suppliers.base import SupplierInvoiceParser
from invoice_price_checker.text import extract_pdf_text, parse_decimal


class GenericSupplierParser(SupplierInvoiceParser):
    supplier_code = "GENERIC"
    display_name = "Generic text invoice"

    line_pattern = re.compile(
        r"^(?P<code>[A-Z0-9][A-Z0-9._/-]{2,})\s+"
        r"(?P<description>.+?)\s+"
        r"(?P<quantity>\d+(?:[,.]\d+)?)\s+"
        r"(?P<unit_price>\d+(?:[,.]\d{1,4})?)\s*"
        r"(?P<currency>EUR|USD|GBP|CHF)?$",
        re.IGNORECASE,
    )

    def parse(self, file: BinaryIO) -> ParsedInvoice:
        text = extract_pdf_text(file)
        lines = self._parse_lines(text)
        return ParsedInvoice(
            supplier_code=self.supplier_code,
            invoice_number=self._find_invoice_number(text),
            invoice_date=None,
            lines=lines,
            metadata={
                "supplier_code": self.supplier_code,
                "parser": self.__class__.__name__,
                "invoice_number": self._find_invoice_number(text),
                "invoice_date": None,
                "line_count": len(lines),
            },
        )

    def _parse_lines(self, text: str) -> pd.DataFrame:
        records: list[dict[str, object]] = []
        for raw_line in text.splitlines():
            line = " ".join(raw_line.split())
            match = self.line_pattern.match(line)
            if not match:
                continue
            unit_price = parse_decimal(match.group("unit_price"))
            if unit_price is None:
                continue
            records.append(
                {
                    "supplier_article_code": match.group("code").strip(),
                    "description": match.group("description").strip(),
                    "quantity": parse_decimal(match.group("quantity")),
                    "unit_price": unit_price,
                    "currency": (match.group("currency") or "EUR").upper(),
                    "raw_line": raw_line,
                }
            )
        return pd.DataFrame(
            records,
            columns=[
                "supplier_article_code",
                "description",
                "quantity",
                "unit_price",
                "currency",
                "raw_line",
            ],
        )

    def _find_invoice_number(self, text: str) -> str | None:
        match = re.search(
            r"(?:invoice|facture|rechnung)\s*(?:number|no\.?|n[°o])?\s*[:#-]?\s*([A-Z0-9/-]+)",
            text,
            re.IGNORECASE,
        )
        return match.group(1) if match else None
